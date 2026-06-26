"""
Background task system — run slow operations in daemon threads.

s13 新增：
  - should_run_background: 判断是否走后台（显式请求优先 + 启发式兜底）
  - start_background_task: 启动后台线程，返回 bg_id
  - collect_background_results: 收集完成的通知，格式化为 <task_notification>
"""

import threading
import subprocess

from agent.config import WORKDIR

# ── State ──

_bg_counter = 0
background_tasks: dict[str, dict] = {}   # bg_id → {tool_use_id, command, status}
background_results: dict[str, str] = {}   # bg_id → output
background_lock = threading.Lock()

# ── Heuristic ──

_SLOW_KEYWORDS = [
    "install", "build", "test", "deploy", "compile",
    "docker build", "pip install", "npm install",
    "cargo build", "pytest", "make",
]


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    """Fallback heuristic: commands likely to take > 30s."""
    if tool_name != "run_bash":
        return False
    cmd = tool_input.get("command", "").lower()
    return any(kw in cmd for kw in _SLOW_KEYWORDS)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    """Model explicit request takes priority; fallback to heuristic."""
    if tool_input.get("run_in_background"):
        return True
    return is_slow_operation(tool_name, tool_input)


# ── Lifecycle ──

def _execute_bash(command: str) -> str:
    """Run a shell command, same logic as run_bash."""
    try:
        r = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, timeout=600,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (600s)"


def start_background_task(tool_use_id: str, tool_name: str, tool_input: dict) -> str:
    """
    Run tool in a daemon thread. Returns background task ID.
    """
    global _bg_counter

    if tool_name != "run_bash":
        raise ValueError(f"Background tasks only support run_bash, got {tool_name}")

    command = tool_input.get("command", "")

    with background_lock:
        _bg_counter += 1
        bg_id = f"bg_{_bg_counter:04d}"
        background_tasks[bg_id] = {
            "tool_use_id": tool_use_id,
            "command": command,
            "status": "running",
        }

    def worker():
        result = _execute_bash(command)
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = result

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return bg_id


def collect_background_results() -> list[str]:
    """
    Collect completed background results as <task_notification> messages.
    Returns a list of formatted notification strings.
    """
    with background_lock:
        ready_ids = [
            bid for bid, task in background_tasks.items()
            if task["status"] == "completed"
        ]

    notifications = []
    for bg_id in ready_ids:
        with background_lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{output[:200]}</summary>\n"
            f"</task_notification>"
        )
    return notifications
