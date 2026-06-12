"""
Task management tool: todo_write.
"""

from agent.config import WORKDIR

# In-memory TODO state (cleared on process exit)
CURRENT_TODOS: list[dict] = []


def run_todo_write(todos: list) -> str:
    for i, t in enumerate(todos):
        if "content" not in t or "status" not in t:
            return f"Error: todos[{i}] missing 'content' or 'status'"
        if t["status"] not in ("pending", "in_progress", "completed"):
            return f"Error: todos[{i}] has invalid status '{t['status']}'"

    global CURRENT_TODOS
    CURRENT_TODOS = todos

    tasks_dir = WORKDIR / ".tasks"
    tasks_dir.mkdir(exist_ok=True)
    tasks_file = tasks_dir / "current_todos.json"
    import json
    tasks_file.write_text(json.dumps(todos, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["\n## Current Tasks"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": ">", "completed": "[x]"}[t.get("status", "pending")]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"
