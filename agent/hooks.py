# hooks.py — migrated from root directory
# PreToolUse / PostToolUse hook system

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

HookAction = Literal["continue", "block"]


@dataclass
class HookResult:
    action: HookAction = "continue"
    reason: Optional[str] = None
    args: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None


def before_tool(tool_name: str, args: Dict[str, Any], context: Dict[str, Any]) -> HookResult:
    """
    PreToolUse Hook — called before tool execution.
    Uses: logging, parameter checks, parameter modification, blocking.
    """
    loop_count = context.get("loop_count")
    print(f"[HOOK before_tool] loop={loop_count}, tool={tool_name}, args={args}")

    # Block .env file modifications
    if tool_name in ["write_file", "edit_file"]:
        path = args.get("path", "")
        if path.endswith(".env") or ".env" in path:
            return HookResult(
                action="block",
                reason="Hook blocked: editing .env files is not allowed.",
            )

    # Block .env file reads
    if tool_name == "read_file":
        path = args.get("path", "")
        if path.endswith(".env") or ".env" in path:
            return HookResult(
                action="block",
                reason="Hook blocked: reading .env files is not allowed.",
            )

    # Block bash commands that reference .env files
    if tool_name == "run_bash":
        cmd = args.get("command", "")
        if ".env" in cmd:
            return HookResult(
                action="block",
                reason="Hook blocked: bash commands referencing .env files are not allowed.",
            )

    return HookResult(action="continue", args=args)


def after_tool(
    tool_name: str,
    args: Dict[str, Any],
    result: Any,
    context: Dict[str, Any],
) -> HookResult:
    """
    PostToolUse Hook — called after tool execution.
    Uses: logging, audit, auto-formatting, result modification.
    """
    loop_count = context.get("loop_count")
    print(f"[HOOK after_tool] loop={loop_count}, tool={tool_name}, result={result}")

    # Print TODO progress on success
    if tool_name == "todo_write" and isinstance(result, dict) and result.get("ok"):
        todos_info = result.get("result", "")
        print(f"[TODO] {todos_info}")

    # Audit info for edit_file
    if tool_name == "edit_file":
        result = {
            "ok": True,
            "tool_result": result,
            "audit": "PostToolUse Hook checked edit_file result.",
        }

    return HookResult(action="continue", result=result)
