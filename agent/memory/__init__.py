"""
Memory package — 跨压缩、跨会话的知识积累。

核心原则：压缩会丢细节，要有一层不丢的。

子模块：
    storage:      记忆文件存储和索引管理
    loader:       记忆加载和选择逻辑
    extractor:    从对话中提取记忆
    consolidator: 记忆整理和去重
"""

from agent.memory.storage import (
    write_memory_file,
    list_memory_files,
    rebuild_index,
    MEMORY_DIR,
)
from agent.memory.loader import load_memories, select_relevant_memories
from agent.memory.extractor import extract_memories
from agent.memory.consolidator import consolidate_memories

__all__ = [
    "write_memory_file",
    "list_memory_files",
    "rebuild_index",
    "load_memories",
    "select_relevant_memories",
    "extract_memories",
    "consolidate_memories",
    "MEMORY_DIR",
]
