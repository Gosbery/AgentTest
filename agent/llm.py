"""
LLM client wrapper — uses config for OpenAI-compatible API.
"""

from agent.config import LLM_CLIENT, MODEL_ID, DEFAULT_MAX_TOKENS


def call_llm(messages: list, tools: list, system_prompt: str = None, 
             model: str = None, max_tokens: int = None) -> object:
    """
    Unified LLM call with OpenAI-compatible API.

    Args:
        messages: conversation messages (user/assistant/tool roles)
        tools: list of OpenAI-compatible tool schemas
        system_prompt: optional system prompt
        model: optional model override (for fallback model switching)
        max_tokens: optional max output tokens

    Returns:
        The full response object with .choices[0].message and .choices[0].finish_reason
    """
    sys_messages = messages
    if system_prompt:
        sys_messages = [{"role": "system", "content": system_prompt}] + messages

    # Use provided model or fall back to default
    use_model = model or MODEL_ID
    
    # Build request parameters
    request_params = {
        "model": use_model,
        "messages": sys_messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    
    # Add max_tokens if specified
    if max_tokens:
        request_params["max_tokens"] = max_tokens

    response = LLM_CLIENT.chat.completions.create(**request_params)
    return response
