# hooks.py

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
    PreToolUse Hook

    工具执行前触发。
    可以用于：
    1. 日志
    2. 参数检查
    3. 参数修改
    4. 阻断工具执行
    """

    loop_count = context.get("loop_count")

    print(f"[HOOK before_tool] loop={loop_count}, tool={tool_name}, args={args}")

    # 示例：禁止 edit_file 修改 .env 文件
    if tool_name in ["write_file", "edit_file"]:
        path = args.get("path", "")

        if path.endswith(".env") or ".env" in path:
            return HookResult(
                action="block",
                reason="Hook blocked: editing .env files is not allowed.",
            )

    # 示例：禁止 read_file 读取 .env 文件
    if tool_name == "read_file":
        path = args.get("path", "")

        if path.endswith(".env") or ".env" in path:
            return HookResult(
                action="block",
                reason="Hook blocked: reading .env files is not allowed.",
            )

    return HookResult(action="continue", args=args)

  
def after_tool(
    tool_name: str,
    args: Dict[str, Any],
    result: Any,
    context: Dict[str, Any],
) -> HookResult:
    """
    PostToolUse Hook

    工具执行后触发。
    可以用于：
    1. 日志
    2. 审计
    3. 自动格式化
    4. 修改 tool result
    """

    loop_count = context.get("loop_count")

    print(f"[HOOK after_tool] loop={loop_count}, tool={tool_name}, result={result}")

    # todo_write 成功后打印任务进度
    if tool_name == "todo_write" and isinstance(result, dict) and result.get("ok"):
        todos_info = result.get("result", "")
        print(f"[TODO] {todos_info}")

    # 示例：给 edit_file 成功结果追加审计信息
    if tool_name == "edit_file":
        result = {
            "ok": True,
            "tool_result": result,
            "audit": "PostToolUse Hook checked edit_file result.",
        }

    return HookResult(action="continue", result=result)