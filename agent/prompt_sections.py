"""
System prompt sections — 分段定义和运行时组装。

核心思想：把硬编码的 SYSTEM prompt 拆成独立的 sections，
运行时根据真实状态（工具列表、记忆文件等）按需拼接，
并缓存结果避免重复组装。

设计：
- PROMPT_SECTIONS: 字典，每个 key 是一个主题
- assemble_system_prompt: 根据 context 按需拼接
- get_system_prompt: 带缓存的组装函数
- update_context: 获取真实状态（工具列表、工作目录、记忆等）
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional

from agent.config import WORKDIR
from agent.tools import TOOLS
from agent.memory.loader import get_memory_index_for_system
from agent.skill_loader import SkillLoader

# ============================================================================
# 初始化 Skills 和 Memory
# ============================================================================

_skill_loader = SkillLoader()
_skill_menu_lines = _skill_loader.get_skill_descriptions()
SKILL_MENU = ""
if _skill_menu_lines:
    menu_items = [f"- {name}: {desc}" for name, desc in sorted(_skill_menu_lines.items())]
    SKILL_MENU = "\n".join(menu_items)

# ============================================================================
# PROMPT_SECTIONS: 分段定义
# ============================================================================

PROMPT_SECTIONS = {
    "identity": """你是一个 Claude Code 风格的编程 Agent。
你可以通过工具完成任务。需要外部信息时，优先调用工具，不要猜测。
拿到工具结果后，再继续判断是否需要下一步工具。
当信息足够时，输出最终答案。

重要：在开始执行复杂任务之前，先使用 todo_write 工具列出所有步骤，规划好再动手。
对于复杂的子任务，使用 task 工具委派给子 Agent。""",
    
    "tools": "Available tools will be listed below. Use them to accomplish tasks.",
    
    "workspace": f"Working directory: {WORKDIR}",
    
    "memory": "Relevant memories are injected below when available.",
    
    "skills": SKILL_MENU if SKILL_MENU else "",
}

# ============================================================================
# 缓存相关
# ============================================================================

_last_context_key: Optional[str] = None
_last_prompt: Optional[str] = None

# ============================================================================
# assemble_system_prompt: 按需拼接
# ============================================================================

def assemble_system_prompt(context: Dict[str, Any]) -> str:
    """
    根据 context 的真实状态按需拼接 system prompt。
    
    加载策略：
    - identity: 始终加载
    - tools: 始终加载（工具列表在 context 中）
    - workspace: 始终加载
    - memory: 按需加载（当有记忆索引时）
    - skills: 按需加载（当有 skills 时）
    
    Args:
        context: 包含当前运行态状态的字典
            - enabled_tools: 实际注册的工具列表
            - workspace: 工作目录
            - memories: 记忆索引内容
            - skills: skills 菜单
    
    Returns:
        拼接后的 system prompt
    """
    sections = []
    loaded_sections = []
    
    # 始终加载的 sections
    sections.append(PROMPT_SECTIONS["identity"])
    loaded_sections.append("identity")
    
    sections.append(PROMPT_SECTIONS["tools"])
    loaded_sections.append("tools")
    
    sections.append(PROMPT_SECTIONS["workspace"])
    loaded_sections.append("workspace")
    
    # 按需加载 — 基于真实状态，不是关键词
    memories = context.get("memories", "")
    if memories:
        sections.append(f"<memory-index>\n{memories}\n</memory-index>")
        loaded_sections.append("memory")
    
    skills = context.get("skills", "")
    if skills:
        sections.append(f"<skills>\n{skills}\n</skills>")
        loaded_sections.append("skills")
    
    # 调试输出：显示加载了哪些 sections
    print(f"[assembled] sections: {', '.join(loaded_sections)}")
    
    return "\n\n".join(sections)

# ============================================================================
# get_system_prompt: 缓存避免重复拼接
# ============================================================================

def get_system_prompt(context: Dict[str, Any]) -> str:
    """
    带缓存的 system prompt 组装函数。
    
    当 context 没变时（同一轮对话的多次 LLM 调用），
    直接返回缓存的 prompt，避免重复拼接。
    
    使用 json.dumps 而不是 hash()：
    - Python 内置 hash() 有进程随机化，不适合做稳定 cache key
    - hash() 遇到 list/dict 会报 unhashable type
    
    Args:
        context: 当前运行态状态
    
    Returns:
        组装后的 system prompt
    """
    global _last_context_key, _last_prompt
    
    # 用确定性序列化检测变化
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    
    if key == _last_context_key and _last_prompt:
        print("[cache hit] system prompt unchanged")
        return _last_prompt
    
    # 重新组装
    _last_context_key = key
    _last_prompt = assemble_system_prompt(context)
    return _last_prompt

# ============================================================================
# update_context: 获取真实状态
# ============================================================================

def update_context(context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    获取当前运行态的真实状态，构建 context 字典。
    
    context 反映当前运行态的真实状态：
    - enabled_tools: 实际注册的工具列表
    - workspace: 工作目录
    - memories: 记忆索引内容（从 MEMORY.md 读取）
    - skills: skills 菜单
    
    section 加载基于这些真实状态，不在消息里搜关键词。
    
    Args:
        context: 可选的旧 context（用于增量更新，当前未使用）
    
    Returns:
        更新后的 context 字典
    """
    # 获取记忆索引
    memories = ""
    memory_index = get_memory_index_for_system()
    if memory_index:
        memories = memory_index
    
    # 获取 skills 菜单
    skills = SKILL_MENU
    
    return {
        "enabled_tools": list(TOOLS.keys()),
        "workspace": str(WORKDIR),
        "memories": memories,
        "skills": skills,
    }
