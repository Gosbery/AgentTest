"""
LLM client wrapper — uses config for OpenAI-compatible API.
"""

from agent.config import LLM_CLIENT, MODEL_ID


def call_llm(messages: list, tools: list, system_prompt: str = None) -> object:
    """
    Unified LLM call with OpenAI-compatible API.

    Args:
        messages: conversation messages (user/assistant/tool roles)
        tools: list of OpenAI-compatible tool schemas
        system_prompt: optional system prompt

    Returns:
        The assistant messages object with .content and .tool_calls
    """
    sys_messages = messages
    if system_prompt:
        sys_messages = [{"role": "system", "content": system_prompt}] + messages

    response = LLM_CLIENT.chat.completions.create(
        model=MODEL_ID,
        messages=sys_messages,
        tools=tools,
        tool_choice="auto",
    )
    return response.choices[0].message
