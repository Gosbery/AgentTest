"""
Main agent loop — message flow, tool dispatch, subagent spawning.

Exports:
    run_agent(user_input) -> str
    agent_loop(messages) -> None (modifies messages in place)
"""

import json

from agent.skill_loader import SkillLoader
from agent.llm import call_llm
from agent.tools import TOOLS, TOOL_SCHEMAS, make_tool_schema
from agent.tools.skill import make_load_skill, make_load_skill_schema
from agent.hooks import before_tool, after_tool
from agent.permissions import check_permission
from agent.subagent import spawn_subagent
from agent.compact import (
    apply_compression,
    reactive_compact,
    compact_history,
    compact_tool,
    COMPACT_TOOL_SCHEMA,
    MAX_REACTIVE_RETRIES,
)
from agent.memory import (
    load_memories,
    extract_memories,
    consolidate_memories,
)
from agent.prompt_sections import get_system_prompt, update_context

# Build the skill loader for the load_skill tool
_skill_loader = SkillLoader()

# Create the load_skill tool and schema
_load_skill_func = make_load_skill(_skill_loader)
_load_skill_schema = make_load_skill_schema(_skill_loader)


# Add task tool to parent's tools
TASK_TOOL_SCHEMA = make_tool_schema(
    "task",
    "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
    {"description": {"type": "string"}},
    ["description"],
)

ALL_TOOLS = {
    **TOOLS,
    "task": spawn_subagent,
    "load_skill": _load_skill_func,
    "compact": compact_tool,
}
ALL_TOOL_SCHEMAS = TOOL_SCHEMAS + [
    TASK_TOOL_SCHEMA,
    _load_skill_schema,
    COMPACT_TOOL_SCHEMA,
]


def _append_tool_result(messages: list, tool_call_id: str, result) -> None:
    """Append tool execution result to messages."""
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": result,
    })


# Persistent conversation messages — shared across user turns
_conversation_messages: list = []

# Persistent prompt context — updated each turn
_prompt_context: dict = {}


def _get_messages(user_input: str) -> list:
    """Get or initialize the persistent conversation messages."""
    global _conversation_messages, _prompt_context
    if not _conversation_messages:
        # Initialize context on first call
        _prompt_context = update_context()
    _conversation_messages.append({"role": "user", "content": user_input})
    return _conversation_messages


def reset_conversation() -> None:
    """Reset the persistent conversation history."""
    global _conversation_messages
    _conversation_messages = []
    print("[Conversation reset]")


def run_agent(user_input: str) -> str:
    """
    Run the agent loop for a single user query.

    Messages persist across turns — compact affects the shared history.

    Args:
        user_input: the user's natural language task

    Returns:
        The agent's final text response
    """
    messages = _get_messages(user_input)
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
        Memory Load → Compression → User → LLM → Tool Selection → Permission Check
        → before_tool Hook → Tool Execute → after_tool Hook
        → Tool Result appended → LLM Replan / Final Answer
        → (on exit) Memory Extract + Consolidate
    """
    global _prompt_context
    loop_count = 0
    rounds_since_todo = 0
    reactive_retries = 0
    compact_failures = 0

    while True:
        loop_count += 1

        # Update context and get assembled system prompt
        _prompt_context = update_context(_prompt_context)
        system_prompt = get_system_prompt(_prompt_context)

        # Apply compression pipeline before LLM call
        messages[:] = apply_compression(messages)

        # Load relevant memories and inject into context
        memory_text = load_memories(messages)
        if memory_text:
            messages.append({"role": "user", "content": memory_text})

        # Nag reminder: reset todo counter after 3 rounds without todo_write
        if rounds_since_todo >= 3 and messages:
            messages.append({
                "role": "user",
                "content": "<reminder>请更新你的 todo 列表，保持任务状态可见。</reminder>",
            })
            rounds_since_todo = 0

        try:
            response = call_llm(messages, ALL_TOOL_SCHEMAS, system_prompt)
            # Reset reactive retries on successful call
            reactive_retries = 0
        except Exception as e:
            # Check if it's a prompt_too_long error
            error_str = str(e).lower()
            if "prompt_too_long" in error_str or "context_length" in error_str or "maximum context" in error_str:
                if reactive_retries < MAX_REACTIVE_RETRIES:
                    print(f"[Reactive compact] API error: {e}")
                    messages[:] = reactive_compact(messages)
                    reactive_retries += 1
                    continue
                else:
                    print(f"[Fatal] Max reactive retries exceeded: {e}")
                    raise
            else:
                raise

        messages.append({"role": "assistant", "content": response.content})

        # No tool calls → final answer
        if not response.tool_calls:
            print("\n[AGENT] Final response, no more tool calls")
            # Extract memories from this turn and consolidate if needed
            extract_memories(messages)
            consolidate_memories()
            return

        # Debug: print tool calls
        for tc in response.tool_calls:
            print(f"\n[LLM>Tool] {tc.function.name} | args: {tc.function.arguments}")

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
                print(f"[PERMISSION DENIED] {tool_name}: {reason}")
                _append_tool_result(messages, tc.id, reason)
                continue

            # 2. PreToolUse hook
            pre_result = before_tool(tool_name, args, context)
            if pre_result.action == "block":
                print(f"[HOOK BLOCKED] {tool_name}: {pre_result.reason}")
                _append_tool_result(messages, tc.id, pre_result.reason)
                continue

            if pre_result.args is not None:
                args = pre_result.args

            # 3. Execute tool
            print(f"[TOOL EXEC] {tool_name}({args})")
            tool_func = ALL_TOOLS.get(tool_name)
            try:
                output = tool_func(**args) if tool_func else f"Unknown: {tool_name}"
                tool_result = {"ok": True, "result": output}
            except Exception as e:
                tool_result = {"ok": False, "error": str(e)}
                print(f"[TOOL ERROR] {tool_name}: {e}")

            # Handle compact tool specially
            if tool_name == "compact":
                print("[Compact tool] Model-initiated compaction")
                messages[:] = compact_history(messages)
                _append_tool_result(messages, tc.id, output)
                # End current turn, start fresh with compacted context
                break

            # Reset todo counter if todo_write was called
            if tool_name == "todo_write":
                rounds_since_todo = 0
            else:
                rounds_since_todo += 1

            # 4. PostToolUse hook
            post_result = after_tool(tool_name, args, tool_result, context)
            if post_result.result is not None:
                tool_result = post_result.result

            # Debug: print result summary
            result_preview = str(tool_result)[:200].encode('utf-8', errors='ignore').decode('utf-8', errors='ignore')
            print(f"[TOOL RESULT] {tool_name} => {result_preview}...")

            _append_tool_result(messages, tc.id, tool_result)
