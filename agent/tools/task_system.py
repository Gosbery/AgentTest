"""
Task management system — persistent tasks with dependency tracking.

s12 新增：
  - Task dataclass: id, subject, description, status, owner, blockedBy
  - 5 个工具: create_task, list_tasks, get_task, claim_task, complete_task
  - .tasks/ 目录持久化，每个任务一个 JSON 文件
  - blockedBy 依赖图 + can_start 检查
"""

import json
import time
import random
from dataclasses import dataclass, asdict
from pathlib import Path

from agent.config import WORKDIR


# ============================================================================
# Task Dataclass
# ============================================================================

@dataclass
class Task:
    """任务数据结构。"""
    id: str
    subject: str
    description: str
    status: str          # pending | in_progress | completed
    owner: str | None    # Agent 名（多 Agent 场景）
    blockedBy: list[str] # 依赖的任务 ID 列表
    worktree: str | None = None  # s18: 绑定的 worktree 名称


# ============================================================================
# Storage helpers
# ============================================================================

def _tasks_dir() -> Path:
    """获取 .tasks 目录路径。"""
    tasks_dir = WORKDIR / ".tasks"
    tasks_dir.mkdir(exist_ok=True)
    return tasks_dir


def _task_path(task_id: str) -> Path:
    """获取任务文件路径。"""
    return _tasks_dir() / f"{task_id}.json"


def save_task(task: Task) -> None:
    """保存任务到 JSON 文件。"""
    path = _task_path(task.id)
    path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False), encoding="utf-8")


def load_task(task_id: str) -> Task:
    """从 JSON 文件加载任务。"""
    path = _task_path(task_id)
    if not path.exists():
        raise FileNotFoundError(f"Task {task_id} not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Task(**data)


def list_all_tasks() -> list[Task]:
    """列出所有任务。"""
    tasks = []
    tasks_dir = _tasks_dir()
    for path in tasks_dir.glob("task_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        tasks.append(Task(**data))
    return tasks


def _generate_task_id() -> str:
    """生成任务 ID: timestamp + random hex。"""
    ts = int(time.time())
    rand_hex = format(random.randint(0, 0xFFFF), '04x')
    return f"task_{ts}_{rand_hex}"


# ============================================================================
# Dependency check
# ============================================================================

def can_start(task_id: str) -> bool:
    """
    检查任务是否可以开始。
    
    任务的 blockedBy 中的所有依赖必须已完成。
    不存在的依赖视为 blocked。
    """
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        dep_path = _task_path(dep_id)
        if not dep_path.exists():
            return False  # 依赖不存在 = blocked
        dep = load_task(dep_id)
        if dep.status != "completed":
            return False
    return True


# ============================================================================
# Task tools
# ============================================================================

def create_task(subject: str, description: str = "", 
                blockedBy: list[str] | None = None) -> str:
    """
    创建新任务。
    
    Args:
        subject: 任务简短标题
        description: 任务详细描述
        blockedBy: 依赖的任务 ID 列表
    
    Returns:
        创建结果消息
    """
    task = Task(
        id=_generate_task_id(),
        subject=subject,
        description=description,
        status="pending",
        owner=None,
        blockedBy=blockedBy or [],
    )
    save_task(task)
    
    deps_info = ""
    if task.blockedBy:
        deps_info = f", blocked by: {task.blockedBy}"
    
    return f"Created task {task.id}: {subject}{deps_info}"


def list_tasks() -> str:
    """
    列出所有任务及其状态。
    
    Returns:
        任务列表摘要
    """
    tasks = list_all_tasks()
    if not tasks:
        return "No tasks found."
    
    lines = ["\n## Task List"]
    for t in tasks:
        icon = {"pending": " ", "in_progress": ">", "completed": "[x]"}[t.status]
        deps = f" (blocked by: {t.blockedBy})" if t.blockedBy else ""
        owner = f" @{t.owner}" if t.owner else ""
        lines.append(f"  [{icon}] {t.id}: {t.subject}{owner}{deps}")
    
    return "\n".join(lines)


def get_task(task_id: str) -> str:
    """
    获取任务完整详情。
    
    Args:
        task_id: 任务 ID
    
    Returns:
        任务 JSON 详情
    """
    try:
        task = load_task(task_id)
        return json.dumps(asdict(task), indent=2, ensure_ascii=False)
    except FileNotFoundError as e:
        return str(e)


def claim_task(task_id: str, owner: str = "agent") -> str:
    """
    认领任务。
    
    设置 owner，状态从 pending -> in_progress。
    如果任务已被认领或依赖未完成，拒绝认领。
    
    Args:
        task_id: 任务 ID
        owner: 认领者名称
    
    Returns:
        认领结果消息
    """
    try:
        task = load_task(task_id)
    except FileNotFoundError as e:
        return str(e)
    
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    
    if not can_start(task_id):
        deps = [d for d in task.blockedBy 
                if not _task_path(d).exists() or load_task(d).status != "completed"]
        return f"Blocked by: {deps}"
    
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    
    return f"Claimed {task_id} ({task.subject})"


def complete_task(task_id: str) -> str:
    """
    完成任务。
    
    设置状态为 completed，并找出被解锁的下游任务。
    
    Args:
        task_id: 任务 ID
    
    Returns:
        完成结果消息
    """
    try:
        task = load_task(task_id)
    except FileNotFoundError as e:
        return str(e)
    
    task.status = "completed"
    save_task(task)
    
    # 找出被解锁的下游任务
    unblocked = []
    for t in list_all_tasks():
        if t.status == "pending" and t.blockedBy and can_start(t.id):
            unblocked.append(t.subject)
    
    msg = f"Completed {task_id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
    
    return msg
