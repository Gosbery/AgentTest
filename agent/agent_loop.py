"""
Main agent loop — message flow, tool dispatch, subagent spawning.

Exports:
    run_agent(user_input) -> str
    agent_loop(messages) -> None (modifies messages in place)
"""

import json

from agent.llm import call_llm
from agent.tools import TOOLS, TOOL_SCHEMAS, make_tool_schema
from agent.hooks import before_tool, after_tool
from agent.permissions import check_permission
from agent.subagent import spawn_subagent


# System prompt for the main agent
SYSTEM_PROMPT = """
你是一个 Claude Code 风格的编程 Agent。
你可以通过工具完成任务。需要外部信息时，优先调用工具，不要猜测。
拿到工具结果后，再继续判断是否需要下一步工具。
当信息足够时，输出最终答案。

重要：在开始执行复杂任务之前，先使用 todo_write 工具列出所有步骤，规划好再动手。
对于复杂的子任务，使用 task 工具委派给子 Agent。
"""


# Add task tool to parent's tools
TASK_TOOL_SCHEMA = make_tool_schema(
    "task",
    "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
    {"description": {"type": "string"}},
    ["description"],
)

ALL_TOOLS = {**TOOLS, "task": spawn_subagent}
ALL_TOOL_SCHEMAS = TOOL_SCHEMAS + [TASK_TOOL_SCHEMA]


def _append_tool_result(messages: list, tool_call_id: str, result) -> None:
    """Append tool execution result to messages."""
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": result,
    })


def run_agent(user_input: str) -> str:
    """
    Run the agent loop for a single user query.

    Args:
        user_input: the user's natural language task

    Returns:
        The agent's final text response
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]
    agent_loop(messages)

    # Return the last assistant text response
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        if block.get("text", "").strip():
                            return block["text"]
                    elif hasattr(block, "text") and block.text.strip():
                        return block.text
    return "(no response)"


def agent_loop(messages: list) -> None:
    """
    Main agent loop. Modifies messages in place.

    Flow:
        User → LLM → Tool Selection → Permission Check
        → before_tool Hook → Tool Execute → after_tool Hook
        → Tool Result appended → LLM Replan / Final Answer
    """
    loop_count = 0
    rounds_since_todo = 0

    while True:
        loop_count += 1

        # Nag reminder: reset todo counter after 3 rounds without todo_write
        if rounds_since_todo >= 3 and messages:
            messages.append({
                "role": "user",
                "content": "<reminder>请更新你的 todo 列表，保持任务状态可见。</reminder>",
            })
            rounds_since_todo = 0

        response = call_llm(messages, ALL_TOOL_SCHEMAS, SYSTEM_PROMPT)
        messages.append({"role": "assistant", "content": response.content})

        # No tool calls → final answer
        if not response.tool_calls:
            return

        for tc in response.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            context = {
                "loop_count": loop_count,
                "messages": messages,
                "tool_call_id": tc.id,
            }

            # 1. Permission check
            allowed, reason = check_permission(tool_name)
            if not allowed:
                _append_tool_result(messages, tc.id, reason)
                continue

            # 2. PreToolUse hook
            pre_result = before_tool(tool_name, args, context)
            if pre_result.action == "block":
                _append_tool_result(messages, tc.id, pre_result.reason)
                continue

            if pre_result.args is not None:
                args = pre_result.args

            # 3. Execute tool
            tool_func = ALL_TOOLS.get(tool_name)
            try:
                output = tool_func(**args) if tool_func else f"Unknown: {tool_name}"
                tool_result = {"ok": True, "result": output}
            except Exception as e:
                tool_result = {"ok": False, "error": str(e)}

            # Reset todo counter if todo_write was called
            if tool_name == "todo_write":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            # 4. PostToolUse hook
            post_result = after_tool(tool_name, args, tool_result, context)
            if post_result.result is not None:
                tool_result = post_result.result

            _append_tool_result(messages, tc.id, tool_result)
