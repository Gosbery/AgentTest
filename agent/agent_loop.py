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
from agent.tools.background_tasks import (
    should_run_background,
    start_background_task,
    collect_background_results,
)
from agent.tools.skill import make_load_skill, make_load_skill_schema
from agent.hooks import before_tool, after_tool
from agent.permissions import check_permission
from agent.subagent import spawn_subagent
from agent.compact import (
    apply_compression,
    reactive_compact as compact_reactive_compact,
    compact_history,
    compact_tool,
    COMPACT_TOOL_SCHEMA,
    MAX_REACTIVE_RETRIES,
)
from agent.error_recovery import (
    RecoveryState,
    with_retry,
    is_prompt_too_long_error,
    reactive_compact,
)
from agent.config import (
    DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES,
    CONTINUATION_PROMPT,
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
        Memory Load → Compression → User → [try] LLM [except] -> Tool Selection
        -> Permission Check -> before_tool Hook -> Tool Execute -> after_tool Hook
        -> Tool Result appended -> LLM Replan / Final Answer
        -> (on exit) Memory Extract + Consolidate
        
    Error Recovery (s11):
        - Path 1: max_tokens -> escalate 8K->64K, then continuation prompt (max 3)
        - Path 2: prompt_too_long -> reactive compact -> retry (once)
        - Path 3: 429/529 -> exponential backoff with jitter (max 10), fallback model
    """
    global _prompt_context
    loop_count = 0
    rounds_since_todo = 0
    
    # s11: Error recovery state
    recovery_state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS

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

        # ── LLM call: with_retry handles 429/529, outer handles rest ──
        try:
            response = with_retry(
                lambda mt=max_tokens, mdl=recovery_state.current_model: 
                    call_llm(messages, ALL_TOOL_SCHEMAS, system_prompt, model=mdl, max_tokens=mt),
                recovery_state
            )
            # Extract message from response
            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            
        except Exception as e:
            # Path 2: prompt_too_long -> reactive compact (once)
            if is_prompt_too_long_error(e):
                if not recovery_state.has_attempted_reactive_compact:
                    print(f"  \033[31m[prompt_too_long] {str(e)[:100]}\033[0m")
                    messages[:] = reactive_compact(messages)
                    recovery_state.has_attempted_reactive_compact = True
                    continue
                print("  \033[31m[unrecoverable] still too long after compact\033[0m")
                messages.append({"role": "assistant", "content": 
                    "[Error] Context too large, cannot continue."})
                return
            # Unrecoverable
            name = type(e).__name__
            print(f"  \033[31m[unrecoverable] {name}: {str(e)[:100]}\033[0m")
            messages.append({"role": "assistant", "content": 
                f"[Error] {name}: {str(e)[:200]}"})
            return

        # ── Path 1: max_tokens -> escalate or continue ──
        # OpenAI API uses finish_reason="length" for truncation
        if finish_reason == "length":
            # First escalation: don't append truncated output, retry same request
            if not recovery_state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                recovery_state.has_escalated = True
                print(f"  \033[33m[max_tokens] escalating "
                      f"{DEFAULT_MAX_TOKENS} -> {ESCALATED_MAX_TOKENS}\033[0m")
                continue
            # 64K still truncated: save truncated output + continuation prompt
            messages.append({"role": "assistant", "content": message.content})
            if recovery_state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                recovery_state.recovery_count += 1
                print(f"  \033[33m[max_tokens] continuation "
                      f"{recovery_state.recovery_count}/{MAX_RECOVERY_RETRIES}\033[0m")
                continue
            print("  \033[31m[max_tokens] recovery limit reached\033[0m")
            return
        
        # Normal completion: append assistant response
        messages.append({"role": "assistant", "content": message.content})

        # No tool calls → final answer
        if not message.tool_calls:
            print("\n[AGENT] Final response, no more tool calls")
            # Extract memories from this turn and consolidate if needed
            extract_memories(messages)
            consolidate_memories()
            return

        # Debug: print tool calls
        for tc in message.tool_calls:
            print(f"\n[LLM>Tool] {tc.function.name} | args: {tc.function.arguments}")

        for tc in message.tool_calls:
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

            # 3. Execute tool (sync or background)
            print(f"[TOOL EXEC] {tool_name}({args})")
            if should_run_background(tool_name, args):
                bg_id = start_background_task(tc.id, tool_name, args)
                output = f"[Background task {bg_id} started] Result will be available when complete."
                tool_result = {"ok": True, "result": output}
            else:
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

        # ── Collect background task notifications ──
        bg_notifications = collect_background_results()
        if bg_notifications:
            user_content = []
            for notif in bg_notifications:
                user_content.append({"type": "text", "text": notif})
            messages.append({"role": "user", "content": user_content})
            print(f"[BG] Injected {len(bg_notifications)} background task notification(s)")
