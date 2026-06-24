"""
Memory loader — 记忆加载和选择逻辑。

两条加载路径：
1. 索引常驻 SYSTEM: build_system() 每轮重建 SYSTEM 时读取 MEMORY.md
2. 相关记忆按需注入: load_memories() 通过 LLM side-query 选择相关记忆

关键设计：
- 索引常驻 system prompt（可被 prompt cache 缓存）
- 文件内容按需注入（按 filename/description 匹配当前对话）
- 最多选择 5 条记忆，控制开销
- side-query 失败时降级到关键词匹配
"""

import json
import re
from typing import List, Dict

from agent.config import LLM_CLIENT, MODEL_ID
from agent.memory.storage import list_memory_files, read_memory_file

# 最多选择的记忆数量
MAX_SELECTED_MEMORIES = 5


def select_relevant_memories(
    messages: List[Dict],
    max_items: int = MAX_SELECTED_MEMORIES,
) -> List[str]:
    """
    使用 LLM side-query 选择与当前对话相关的记忆。

    流程：
    1. 列出所有记忆文件的 name + description
    2. 构建目录清单
    3. 发给 LLM 做轻量 side-query
    4. 解析返回的 JSON 数组（记忆索引）
    5. 返回选中的文件名列表

    Args:
        messages: 当前对话消息列表
        max_items: 最多选择的记忆数量

    Returns:
        选中的记忆文件名列表

    Example:
        >>> selected = select_relevant_memories(messages)
        >>> print(selected)
        ['user-preference-tabs.md', 'project-auth-rewrite.md']
    """
    files = list_memory_files()
    if not files:
        return []

    # 构建目录清单: "0: user-preference-tabs — User prefers tabs..."
    catalog_lines = []
    for i, f in enumerate(files):
        catalog_lines.append(f"{i}: {f['name']} — {f['description']}")
    catalog = "\n".join(catalog_lines)

    # 提取最近对话用于匹配
    recent = _format_recent_messages(messages[-10:])

    # 构建 side-query prompt
    prompt = f"""Select relevant memory indices for the current conversation.
Return a JSON array of indices (e.g., [0, 2, 4]).
If no memories are relevant, return [].
Do not select more than {max_items} memories.
Only select memories that are truly useful for the current context.

Recent conversation:
{recent}

Memory catalog:
{catalog}
"""

    try:
        # LLM side-query
        response = LLM_CLIENT.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.0,
        )

        response_text = response.choices[0].message.content.strip()

        # 解析 JSON 数组
        indices = _parse_json_array(response_text)

        # 验证索引范围并返回文件名
        selected = []
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(files):
                selected.append(files[idx]["filename"])
                if len(selected) >= max_items:
                    break

        if selected:
            print(f"[Memory side-query] Selected {len(selected)} memories: {selected}")

        return selected

    except Exception as e:
        print(f"[Memory side-query] LLM selection failed: {e}, falling back to keyword matching")
        # 降级到关键词匹配
        return _keyword_fallback(recent, files, max_items)


def _format_recent_messages(messages: List[Dict]) -> str:
    """
    格式化最近的消息用于匹配。

    Args:
        messages: 最近的消息列表

    Returns:
        格式化后的文本
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, list):
            # 处理复杂内容
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = " ".join(text_parts)

        # 截断过长的内容
        if len(str(content)) > 500:
            content = str(content)[:500] + "..."

        parts.append(f"[{role}]: {content}")

    return "\n".join(parts)


def _parse_json_array(text: str) -> List[int]:
    """
    从文本中解析 JSON 数组。

    Args:
        text: 包含 JSON 数组的文本

    Returns:
        解析后的整数列表
    """
    # 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [int(x) for x in result if isinstance(x, (int, float))]
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 [...] 部分
    match = re.search(r"\[.*?\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [int(x) for x in result if isinstance(x, (int, float))]
        except json.JSONDecodeError:
            pass

    return []


def _keyword_fallback(
    recent_text: str,
    files: List[Dict],
    max_items: int,
) -> List[str]:
    """
    降级到关键词匹配选择记忆。

    当 LLM side-query 失败时使用此方法。
    通过检查 name 和 description 中的关键词是否出现在最近对话中。

    Args:
        recent_text: 最近对话的格式化文本
        files: 记忆文件列表
        max_items: 最多选择的数量

    Returns:
        选中的文件名列表
    """
    recent_lower = recent_text.lower()
    scored = []

    for f in files:
        score = 0
        name_lower = f["name"].lower()
        desc_lower = f["description"].lower()

        # 检查 name 中的词
        for word in re.split(r"[-_\s]+", name_lower):
            if len(word) > 3 and word in recent_lower:
                score += 1

        # 检查 description 中的词
        for word in re.split(r"[\s]+", desc_lower):
            if len(word) > 4 and word in recent_lower:
                score += 1

        if score > 0:
            scored.append((score, f["filename"]))

    # 按分数排序，取前 N 个
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [filename for _, filename in scored[:max_items]]

    if selected:
        print(f"[Memory keyword] Selected {len(selected)} memories: {selected}")

    return selected


def load_memories(messages: List[Dict]) -> str:
    """
    加载相关记忆并格式化为可注入上下文的文本。

    这是主入口函数，供 agent_loop 调用。

    Args:
        messages: 当前对话消息列表

    Returns:
        格式化的记忆文本，如果没有相关记忆则返回空字符串

    Example:
        >>> memory_text = load_memories(messages)
        >>> if memory_text:
        ...     # 注入到上下文中
    """
    selected_files = select_relevant_memories(messages)

    if not selected_files:
        return ""

    # 读取选中的记忆文件
    memories = []
    for filename in selected_files:
        content = read_memory_file(filename)
        if content:
            memories.append(content)

    if not memories:
        return ""

    # 格式化输出
    output_parts = ["<loaded-memories>"]
    for mem in memories:
        output_parts.append(mem)
    output_parts.append("</loaded-memories>")

    return "\n\n".join(output_parts)


def get_memory_index_for_system() -> str:
    """
    获取记忆索引用于注入 system prompt。

    Returns:
        格式化的索引文本，用于常驻 system prompt
    """
    from agent.memory.storage import get_memory_index

    index = get_memory_index()
    if not index:
        return ""

    return f"""
<memory-index>
The following memories are available. Relevant ones will be loaded automatically based on context.

{index}
</memory-index>
"""
