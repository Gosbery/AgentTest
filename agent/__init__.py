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
"""

from agent.agent_loop import run_agent, agent_loop, SYSTEM_PROMPT
from agent.subagent import spawn_subagent

__all__ = ["run_agent", "agent_loop", "SYSTEM_PROMPT", "spawn_subagent"]
