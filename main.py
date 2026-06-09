# main.py

import json

from llm import call_llm
from tools import TOOLS
from permissions import check_permission
from hooks import before_tool, after_tool


DEBUG = 1


SYSTEM_PROMPT = """
你是一个最小版 Claude Code / Codex 风格编程助手。
你可以通过工具完成任务。
需要外部信息时，优先调用工具，不要猜测。
拿到工具结果后，再继续判断是否需要下一步工具。
当信息足够时，输出最终答案。

重要：在开始执行复杂任务之前，先使用 todo_write 工具列出所有步骤，规划好再动手。
"""


def log(msg: str):
    """
    Debug 日志函数。

    输入：
        msg: str
            需要打印的调试信息。

    输出：
        None
            不返回值，只在 DEBUG = 1 时打印日志。
    """

    if DEBUG:
        print(f"\n[DEBUG] {msg}")


def append_tool_result(messages: list, tool_call_id: str, result):
    """
    将工具执行结果回灌到 messages。

    输入：
        messages: list
            当前 Agent 的完整消息列表。

        tool_call_id: str
            LLM 本次 tool_call 的 id。

        result:
            工具执行结果，可以是 str、dict、list 等。

    输出：
        None
            直接修改 messages。
    """

    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)

    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        }
    )


def run_agent(user_input: str):
    """
    Mini Claude Code 主 Agent Loop。

    输入：
        user_input: str
            用户输入的自然语言任务。

    输出：
        str
            当模型不再请求 tool_calls 时，返回最终回答。

    执行流程：
        User
        ↓
        LLM
        ↓
        Tool Selection
        ↓
        Permission Check
        ↓
        before_tool Hook
        ↓
        Tool Execute
        ↓
        after_tool Hook
        ↓
        Tool Result 回灌 messages
        ↓
        LLM Replan / Final Answer
    """

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    loop_count = 0
    rounds_since_todo = 0

    while True:
        loop_count += 1

        # Nag reminder: 连续 3 轮没调 todo_write 时注入提醒
        if rounds_since_todo >= 3:
            messages.append({
                "role": "user",
                "content": "<reminder>请更新你的 todo 列表，保持任务状态可见。</reminder>",
            })
            rounds_since_todo = 0

        log(f"Loop #{loop_count}")
        log(f"Messages count: {len(messages)}")

        assistant_msg = call_llm(messages)
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            log("No tool_calls. Final answer.")
            return assistant_msg.content

        log(f"Tool calls count: {len(assistant_msg.tool_calls)}")

        for tool_call in assistant_msg.tool_calls:
            tool_name = tool_call.function.name
            raw_args = tool_call.function.arguments

            log(f"Calling tool: {tool_name}")
            log(f"Raw arguments: {raw_args}")

            try:
                args = json.loads(raw_args)
            except Exception as e:
                log(f"Arguments parse error: {e}")
                args = {}

            context = {
                "loop_count": loop_count,
                "messages": messages,
                "tool_call_id": tool_call.id,
            }

            # 1. Permission Check
            allowed, reason = check_permission(tool_name)

            if not allowed:
                result = {
                    "ok": False,
                    "error": reason,
                }

                log(f"Permission denied: {tool_name}, reason: {reason}")

                append_tool_result(messages, tool_call.id, result)
                continue

            # 2. Tool Exists Check
            tool_func = TOOLS.get(tool_name)

            if tool_func is None:
                result = {
                    "ok": False,
                    "error": f"未知工具: {tool_name}",
                }

                log(f"Unknown tool: {tool_name}")

                append_tool_result(messages, tool_call.id, result)
                continue

            # 3. PreToolUse Hook
            pre_hook_result = before_tool(
                tool_name=tool_name,
                args=args,
                context=context,
            )

            if pre_hook_result.action == "block":
                result = {
                    "ok": False,
                    "error": pre_hook_result.reason,
                }

                log(
                    f"Hook blocked tool: {tool_name}, "
                    f"reason: {pre_hook_result.reason}"
                )

                append_tool_result(messages, tool_call.id, result)
                continue

            if pre_hook_result.args is not None:
                args = pre_hook_result.args

            # 4. Tool Execute
            try:
                tool_output = tool_func(**args)

                result = {
                    "ok": True,
                    "result": tool_output,
                }

            except Exception as e:
                result = {
                    "ok": False,
                    "error": str(e),
                }

            # 如果调用了 todo_write，重置计数器
            if tool_name == "todo_write":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            # 5. PostToolUse Hook
            post_hook_result = after_tool(
                tool_name=tool_name,
                args=args,
                result=result,
                context=context,
            )

            if post_hook_result.result is not None:
                result = post_hook_result.result

            log(f"Tool result: {result}")

            # 6. Tool Result 回灌 messages
            append_tool_result(messages, tool_call.id, result)


def main():
    """
    命令行入口。

    输入：
        None
            通过 input() 获取用户输入。

    输出：
        None
            不返回值，只负责启动交互式 Agent。
    """

    print("Mini CC started. 输入 exit 退出。")

    while True:
        user_input = input("\nUser> ")

        if user_input.strip().lower() in ["exit", "quit"]:
            break

        answer = run_agent(user_input)

        print("\nAssistant>")
        print(answer)


if __name__ == "__main__":
    main()