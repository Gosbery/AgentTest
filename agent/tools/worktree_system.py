"""
Worktree isolation system — git worktree + task-directory binding + event log.

s18 新增：
  - validate_worktree_name: 拒绝路径穿越和非法字符
  - create_worktree: 为任务创建独立目录 + 独立分支
  - bind_task_to_worktree: 把任务和工作目录绑定（不改状态）
  - remove_worktree: 完成后清理（有改动时拒绝）
  - keep_worktree: 保留 worktree 供人工 review
  - log_event: 生命周期事件审计日志
  - run_git: 执行 git 命令，返回 (ok, output)

ASCII topology:
  Main repo (/)
    ├── .worktrees/auth/  (branch: wt/auth)  ← Task #1
    ├── .worktrees/ui/    (branch: wt/ui)     ← Task #2
    ├── .tasks/task_xxx.json (worktree: "auth")
    └── .worktrees/events.jsonl
"""

import json
import re
import subprocess
import time
from pathlib import Path

from agent.config import WORKDIR
from agent.tools.task_system import load_task, save_task


# ============================================================================
# Configuration
# ============================================================================

WORKTREES_DIR = WORKDIR / ".worktrees"
WORKTREES_DIR.mkdir(exist_ok=True)

# Worktree 名称验证：只允许字母、数字、点、下划线、连字符，长度 1-64
VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


# ============================================================================
# Validation
# ============================================================================

def validate_worktree_name(name: str) -> str | None:
    """
    验证 worktree 名称。
    
    Args:
        name: worktree 名称
    
    Returns:
        错误消息（如果无效），None（如果有效）
    """
    if not name:
        return "Worktree name cannot be empty"
    if name == "." or name == "..":
        return f"'{name}' is not a valid worktree name"
    if not VALID_WT_NAME.match(name):
        return (f"Invalid worktree name '{name}': "
                "only letters, digits, dots, underscores, dashes (1-64 chars)")
    return None


# ============================================================================
# Git operations
# ============================================================================

def run_git(args: list[str]) -> tuple[bool, str]:
    """
    执行 git 命令。
    
    Args:
        args: git 命令参数列表
    
    Returns:
        (ok, output) 元组，ok 表示是否成功
    """
    try:
        r = subprocess.run(
            ["git"] + args,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=30
        )
        out = (r.stdout + r.stderr).strip()
        out = out[:5000] if out else "(no output)"
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "Error: git timeout"


# ============================================================================
# Event logging
# ============================================================================

def log_event(event_type: str, worktree_name: str, task_id: str = "") -> None:
    """
    记录生命周期事件到 events.jsonl。
    
    Args:
        event_type: 事件类型（create/remove/keep）
        worktree_name: worktree 名称
        task_id: 关联的任务 ID（可选）
    """
    event = {
        "type": event_type,
        "worktree": worktree_name,
        "task_id": task_id,
        "ts": time.time()
    }
    events_file = WORKTREES_DIR / "events.jsonl"
    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ============================================================================
# Worktree lifecycle
# ============================================================================

def create_worktree(name: str, task_id: str = "") -> str:
    """
    创建 git worktree，可选绑定到任务。
    
    Args:
        name: worktree 名称
        task_id: 要绑定的任务 ID（可选）
    
    Returns:
        创建结果消息
    """
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    
    path = WORKTREES_DIR / name
    if path.exists():
        return f"Worktree '{name}' already exists at {path}"
    
    # 创建 worktree 和新分支
    ok, result = run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
    if not ok:
        return f"Git error: {result}"
    
    # 可选绑定任务
    if task_id:
        bind_task_to_worktree(task_id, name)
    
    log_event("create", name, task_id)
    print(f"  \033[33m[worktree] created: {name} at {path}\033[0m")
    return f"Worktree '{name}' created at {path}"


def bind_task_to_worktree(task_id: str, worktree_name: str) -> str:
    """
    绑定任务到 worktree。只写 worktree 字段，不改任务状态。
    
    Args:
        task_id: 任务 ID
        worktree_name: worktree 名称
    
    Returns:
        绑定结果消息
    """
    try:
        task = load_task(task_id)
        task.worktree = worktree_name
        save_task(task)
        print(f"  \033[33m[bind] {task.subject} → worktree:{worktree_name}\033[0m")
        return f"Bound task {task_id} to worktree '{worktree_name}'"
    except FileNotFoundError as e:
        return str(e)


def _count_worktree_changes(path: Path) -> tuple[int, int]:
    """
    统计 worktree 中未提交的改动。
    
    Args:
        path: worktree 路径
    
    Returns:
        (files, commits) 元组，files 是未提交文件数，commits 是未推送提交数
    """
    try:
        # 未提交文件
        r1 = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10
        )
        files = len([l for l in r1.stdout.strip().splitlines() if l.strip()])
        
        # 未推送提交
        r2 = subprocess.run(
            ["git", "log", "@{push}..HEAD", "--oneline"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=10
        )
        commits = len([l for l in r2.stdout.strip().splitlines() if l.strip()])
        
        return files, commits
    except Exception:
        return -1, -1


def remove_worktree(name: str, discard_changes: bool = False) -> str:
    """
    删除 worktree。有未提交改动时默认拒绝。
    
    Args:
        name: worktree 名称
        discard_changes: 是否强制删除（丢弃改动）
    
    Returns:
        删除结果消息
    """
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    
    path = WORKTREES_DIR / name
    if not path.exists():
        return f"Worktree '{name}' not found"
    
    # 安全检查：有改动时默认拒绝
    if not discard_changes:
        files, commits = _count_worktree_changes(path)
        if files < 0:
            return (f"Cannot verify worktree '{name}' status. "
                    "Use discard_changes=true to force removal.")
        if files > 0 or commits > 0:
            return (f"Worktree '{name}' has {files} uncommitted file(s) "
                    f"and {commits} unpushed commit(s). "
                    "Use discard_changes=true to force removal, "
                    "or keep_worktree to preserve for review.")
    
    # 删除 worktree 目录
    ok1, _ = run_git(["worktree", "remove", str(path), "--force"])
    if not ok1:
        return f"Failed to remove worktree directory for '{name}'"
    
    # 删除分支
    run_git(["branch", "-D", f"wt/{name}"])
    
    log_event("remove", name)
    print(f"  \033[33m[worktree] removed: {name}\033[0m")
    return f"Worktree '{name}' removed"


def keep_worktree(name: str) -> str:
    """
    保留 worktree 供人工 review。分支保留。
    
    Args:
        name: worktree 名称
    
    Returns:
        保留结果消息
    """
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    
    log_event("keep", name)
    print(f"  \033[36m[worktree] kept: {name}\033[0m")
    return f"Worktree '{name}' kept for review (branch: wt/{name})"


# ============================================================================
# Query functions
# ============================================================================

def get_worktree_path(name: str) -> Path | None:
    """
    获取 worktree 的路径。
    
    Args:
        name: worktree 名称
    
    Returns:
        worktree 路径，不存在返回 None
    """
    path = WORKTREES_DIR / name
    return path if path.exists() else None


def list_worktrees() -> list[dict]:
    """
    列出所有 worktree。
    
    Returns:
        worktree 信息列表
    """
    worktrees = []
    if not WORKTREES_DIR.exists():
        return worktrees
    
    for item in WORKTREES_DIR.iterdir():
        if item.is_dir() and item.name != ".git":
            worktrees.append({
                "name": item.name,
                "path": str(item),
                "exists": True
            })
    
    return worktrees
