"""
Memory extractor — 从对话中提取记忆。

提取时机：
    每轮结束时，当 response.stop_reason != "tool_use" 时触发。
    这表示对话告一段落，可以提取新记忆。

提取流程：
    1. 格式化最近对话（最后 10 条消息）
    2. 列出已有记忆避免重复
    3. 调用 LLM 提取用户偏好、约束、项目事实
    4. 解析返回的 JSON 数组
    5. 写入新的记忆文件

提取 prompt 要求返回：
    [{name, type, description, body}, ...]

只有确实有新信息时才写文件。
"""

import json
import re
from typing import List, Dict

from agent.config import LLM_CLIENT, MODEL_ID
from agent.memory.storage import write_memory_file, list_memory_files

# 提取时查看的最近消息数
EXTRACT_LOOKBACK = 10

# 提取 prompt 的最大对话长度（字符）
MAX_DIALOGUE_CHARS = 4000


def extract_memories(messages: List[Dict]) -> int:
    """
    从最近对话中提取新记忆。

    在每轮结束时调用（当 stop_reason != "tool_use"）。

    Args:
        messages: 当前对话消息列表

    Returns:
        提取的新记忆数量

    Example:
        >>> count = extract_memories(messages)
        >>> print(f"Extracted {count} new memories")
    """
    # 格式化最近对话
    dialogue = _format_recent_messages(messages[-EXTRACT_LOOKBACK:])

    if not dialogue.strip():
        return 0

    # 列出已有记忆
    existing = list_memory_files()
    existing_summary = "\n".join(
        f"- {m['name']}: {m['description']}" for m in existing
    )

    # 构建提取 prompt
    prompt = f"""Extract user preferences, constraints, or project facts from the dialogue.
Return a JSON array of objects with: name, type, description, body.

Types:
- user: User preferences (who they are, what they like)
- feedback: How to do things (constraints, rules)
- project: Project context (what's happening, why)
- reference: Where to find things (links, entry points)

If nothing new or already covered, return [].

Existing memories:
{existing_summary if existing_summary else "(none)"}

Dialogue:
{dialogue[:MAX_DIALOGUE_CHARS]}
"""

    try:
        # 调用 LLM 提取
        response = LLM_CLIENT.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.0,
        )

        response_text = response.choices[0].message.content.strip()

        # 解析 JSON 数组
        memories = _parse_memory_array(response_text)

        if not memories:
            print("[Memory extract] No new memories found")
            return 0

        # 写入新记忆
        written_count = 0
        for mem in memories:
            try:
                write_memory_file(
                    name=mem.get("name", "unnamed"),
                    mem_type=mem.get("type", "project"),
                    description=mem.get("description", ""),
                    body=mem.get("body", ""),
                )
                written_count += 1
            except Exception as e:
                print(f"[Memory extract] Failed to write memory: {e}")

        if written_count > 0:
            print(f"[Memory: extracted {written_count} new memories]")

        return written_count

    except Exception as e:
        print(f"[Memory extract] Extraction failed: {e}")
        return 0


def _format_recent_messages(messages: List[Dict]) -> str:
    """
    格式化最近的消息用于提取。

    Args:
        messages: 最近的消息列表

    Returns:
        格式化后的对话文本
    """
    parts = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # 跳过系统消息
        if role == "system":
            continue

        # 处理复杂内容
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[Called tool: {block.get('name', 'unknown')}]")
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[Tool result: {str(block.get('content', ''))[:200]}]")
                else:
                    text_parts.append(str(block))
            content = " ".join(text_parts)

        # 跳过工具结果（通常不包含偏好）
        if role == "tool":
            continue

        # 截断过长的内容
        if len(str(content)) > 1000:
            content = str(content)[:1000] + "..."

        parts.append(f"[{role}]: {content}")

    return "\n".join(parts)


def _parse_memory_array(text: str) -> List[Dict]:
    """
    从 LLM 响应中解析记忆数组。

    Args:
        text: LLM 响应文本

    Returns:
        记忆对象列表
    """
    # 尝试直接解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return _validate_memories(result)
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 [...] 部分
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return _validate_memories(result)
        except json.JSONDecodeError:
            pass

    print(f"[Memory extract] Failed to parse response: {text[:200]}")
    return []


def _validate_memories(memories: List[Dict]) -> List[Dict]:
    """
    验证和清理记忆对象。

    Args:
        memories: 原始记忆对象列表

    Returns:
        验证后的记忆对象列表
    """
    valid = []
    valid_types = {"user", "feedback", "project", "reference"}

    for mem in memories:
        if not isinstance(mem, dict):
            continue

        # 必须有 name 和 body
        if not mem.get("name") or not mem.get("body"):
            continue

        # 验证类型
        mem_type = mem.get("type", "project")
        if mem_type not in valid_types:
            mem_type = "project"

        valid.append({
            "name": str(mem["name"]).strip(),
            "type": mem_type,
            "description": str(mem.get("description", "")).strip(),
            "body": str(mem["body"]).strip(),
        })

    return valid
