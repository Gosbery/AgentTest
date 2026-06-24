"""
Agent package — a Claude Code style coding agent harness.

Core modules:
    config:       centralized configuration
    llm:          LLM client wrapper
    agent_loop:   main agent loop with tool dispatch
    hooks:        before_tool / after_tool hook system
    permissions:  tool permission control
    tools:        all tool implementations
    subagent:     subagent spawning with context isolation
    compact:      context compression pipeline
    memory:       cross-session memory (storage, loading, extraction, consolidation)
    prompt_sections: runtime system prompt assembly with caching
"""

from agent.agent_loop import run_agent, agent_loop, reset_conversation
from agent.subagent import spawn_subagent
from agent.memory import (
    write_memory_file,
    list_memory_files,
    load_memories,
    extract_memories,
    consolidate_memories,
)
from agent.prompt_sections import (
    get_system_prompt,
    update_context,
    assemble_system_prompt,
    PROMPT_SECTIONS,
)

__all__ = [
    "run_agent",
    "agent_loop",
    "spawn_subagent",
    "reset_conversation",
    "write_memory_file",
    "list_memory_files",
    "load_memories",
    "extract_memories",
    "consolidate_memories",
    "get_system_prompt",
    "update_context",
    "assemble_system_prompt",
    "PROMPT_SECTIONS",
]
