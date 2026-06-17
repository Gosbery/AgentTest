"""
Subagent runner — spawns sub-agents with fresh messages[] for context isolation.

Key design:
- Fresh messages[] per subagent (no main conversation pollution)
- Limited toolset (no task tool — prevents recursive spawning)
- Returns only final text summary (intermediate process discarded)
- Subagent tool calls still go through hooks and permissions
"""

import json

from agent.config import MODEL_ID, DENY_LIST
from agent.llm import call_llm
from agent.tools import TOOLS, TOOL_SCHEMAS, make_tool_schema
from agent.tools.filesystem import read_file, write_file, edit_file, glob_files
from agent.tools.shell import run_bash
from agent.hooks import before_tool, after_tool
from agent.permissions import check_permission


# Subagent tools — NO task tool to prevent recursive spawning
SUB_TOOL_NAMES = ["run_bash", "read_file", "write_file", "edit_file", "glob_files"]

SUB_TOOLS = [s for s in TOOL_SCHEMAS if s["function"]["name"] in SUB_TOOL_NAMES]

SUB_TOOL_HANDLERS = {name: TOOLS[name] for name in SUB_TOOL_NAMES}


def _extract_text(content) -> str:
    """Extract text content from an LLM response."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif hasattr(block, "text"):
                texts.append(block.text)
        return "\n".join(texts)
    return str(content)


def spawn_subagent(description: str) -> str:
    """
    Spawn a subagent with fresh messages[], return summary only.

    The subagent gets its own independent while loop with a fresh messages list.
    After completion (or 30 turn safety limit), only the final text response
    is returned — all intermediate tool calls and reasoning are discarded.

    File system side effects (written/edited files) persist in the workspace.
    """
    print("\n[Subagent spawned]")

    messages = [{"role": "user", "content": description}]

    system_prompt = (
        f"You are a coding agent at the current working directory. "
        "Complete the task you were given, then return a concise summary. "
        "Do not delegate further."
    )

    for turn in range(30):
        response = call_llm(messages, SUB_TOOLS, system_prompt)
        messages.append({"role": "assistant", "content": response.content})

        if not response.tool_calls:
            break

        results = []
        for tc in response.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            # Permission check (subagent also respects permissions)
            allowed, reason = check_permission(tool_name)
            if not allowed:
                results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": reason,
                })
                continue

            # PreToolUse hook
            context = {"loop_count": turn, "messages": messages, "tool_call_id": tc.id}
            pre_result = before_tool(tool_name, args, context)
            if pre_result.action == "block":
                results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": pre_result.reason,
                })
                continue

            if pre_result.args is not None:
                args = pre_result.args

            # Execute tool
            handler = SUB_TOOL_HANDLERS.get(tool_name)
            try:
                output = handler(**args) if handler else f"Unknown: {tool_name}"
                tool_result = {"ok": True, "result": output}
            except Exception as e:
                tool_result = {"ok": False, "error": str(e)}

            # PostToolUse hook
            post_result = after_tool(tool_name, args, tool_result, context)
            if post_result.result is not None:
                tool_result = post_result.result

            print(f"  [sub] {tool_name}: {str(tool_result)[:100]}")

            results.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": str(tool_result),
            })

        messages.extend(results)

    # Extract final text summary — find the last assistant message WITHOUT tool calls
    # (that's the true final answer, not an intermediate "let me continue" response)
    result = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            text = _extract_text(msg.get("content", ""))
            if text:
                result = text
                break

    if not result:
        result = "Subagent stopped after 30 turns without final answer."

    print("[Subagent done]")
    return result
