"""
上下文压缩管线 — 四层压缩策略。

核心原则：便宜的先跑，贵的后跑。

压缩层级：
  L1: snip_compact — 裁掉中间旧对话（0 次 API 调用）
  L2: micro_compact — 旧工具结果替换为占位符（0 次 API 调用）
  L3: tool_result_budget — 大工具输出落盘到磁盘（0 次 API 调用）
  L4: compact_history — LLM 生成全量摘要（1 次 API 调用）
  应急: reactive_compact — API 报错时激进裁剪（1 次 API 调用）
"""

import json
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from agent.config import LLM_CLIENT, MODEL_ID

# =============================================================================
# 常量配置
# =============================================================================

# L1: 触发裁剪的最大消息数
MAX_MESSAGES = 50
KEEP_HEAD = 3  # 保留头部消息数（初始上下文）
# 保留尾部 = MAX_MESSAGES - KEEP_HEAD - 1（减1是因为占位符本身也算一条）

# L2: 保留最近 N 条工具结果的完整内容
KEEP_RECENT_TOOL_RESULTS = 3
TOOL_RESULT_PLACEHOLDER = "[Earlier tool result compacted. Re-run if needed.]"

# L3: 工具结果总字节数上限
MAX_TOOL_RESULT_BYTES = 200_000  # 200KB
PERSIST_DIR = ".task_outputs/tool-results"
PREVIEW_CHARS = 2000  # 预览保留的字符数

# L4: 自动触发压缩的 token 阈值（通过字符数估算）
# 粗略估算：英文约 4 字符/token，中文约 1.5 字符/token
AUTOCOMPACT_TOKEN_THRESHOLD = 80_000
AUTOCOMPACT_CHAR_THRESHOLD = AUTOCOMPACT_TOKEN_THRESHOLD * 3  # 约 240K 字符

# 熔断器：连续失败 N 次后停止重试
MAX_CONSECUTIVE_FAILURES = 3

# 应急压缩：保留最后 N 条消息
REACTIVE_KEEP_TAIL = 5
MAX_REACTIVE_RETRIES = 1

# =============================================================================
# L1: snip_compact — 裁掉中间旧对话
# =============================================================================

def snip_compact(messages: List[Dict], max_messages: int = MAX_MESSAGES) -> List[Dict]:
    """
    裁掉对话历史中间的消息。

    保留头部（初始上下文）和尾部（最近工作），删除中间部分。

    Args:
        messages: 对话消息列表
        max_messages: 最大消息数阈值，超过此值触发裁剪

    Returns:
        裁剪后的消息列表

    Example:
        >>> msgs = [{"role": "user", "content": f"msg {i}"} for i in range(60)]
        >>> result = snip_compact(msgs)  # 保留头3条 + 占位符 + 尾46条
    """
    if len(messages) <= max_messages:
        return messages

    # -1 是因为占位符本身也算一条消息
    keep_tail = max_messages - KEEP_HEAD - 1
    snipped_count = len(messages) - KEEP_HEAD - keep_tail

    placeholder = {
        "role": "user",
        "content": f"[snipped {snipped_count} messages from conversation middle]"
    }

    result = messages[:KEEP_HEAD] + [placeholder] + messages[-keep_tail:]
    print(f"[L1 snip_compact] Removed {snipped_count} messages from middle")
    return result


# =============================================================================
# L2: micro_compact — 旧工具结果替换为占位符
# =============================================================================

def _collect_tool_result_indices(messages: List[Dict]) -> List[int]:
    """
    收集所有工具角色消息的索引。

    Args:
        messages: 对话消息列表

    Returns:
        工具消息的索引列表
    """
    return [i for i, msg in enumerate(messages) if msg.get("role") == "tool"]


def micro_compact(messages: List[Dict]) -> List[Dict]:
    """
    将旧的工具结果替换为占位符文本。

    只保留最近 N 条工具结果的完整内容，更早的替换为占位符。

    Args:
        messages: 对话消息列表

    Returns:
        修改后的消息列表（原地修改）

    Note:
        只压缩内容长度超过 120 字符的工具结果
    """
    tool_indices = _collect_tool_result_indices(messages)

    if len(tool_indices) <= KEEP_RECENT_TOOL_RESULTS:
        return messages

    # 需要压缩的索引（除了最近 N 条）
    indices_to_compact = tool_indices[:-KEEP_RECENT_TOOL_RESULTS]

    compacted_count = 0
    for idx in indices_to_compact:
        msg = messages[idx]
        content = msg.get("content", "")

        # 只压缩内容 substantial 的
        if len(str(content)) > 120:
            msg["content"] = TOOL_RESULT_PLACEHOLDER
            compacted_count += 1

    if compacted_count > 0:
        print(f"[L2 micro_compact] Compacted {compacted_count} old tool results")

    return messages


# =============================================================================
# L3: tool_result_budget — 大工具输出落盘到磁盘
# =============================================================================

def _ensure_persist_dir() -> Path:
    """
    确保落盘目录存在。

    Returns:
        落盘目录路径
    """
    persist_path = Path(PERSIST_DIR)
    persist_path.mkdir(parents=True, exist_ok=True)
    return persist_path


def _persist_large_output(tool_call_id: str, content: str) -> str:
    """
    将大工具输出保存到磁盘，返回带预览的占位符。

    Args:
        tool_call_id: 工具调用 ID，用于生成文件名
        content: 要保存的完整内容

    Returns:
        占位符字符串，包含文件路径和预览内容
    """
    persist_path = _ensure_persist_dir()

    # 从 tool_call_id 和时间戳生成文件名
    safe_id = tool_call_id.replace("-", "")[:16]
    timestamp = int(time.time())
    filename = f"result_{timestamp}_{safe_id}.txt"
    filepath = persist_path / filename

    # 写入完整内容到磁盘
    filepath.write_text(content, encoding="utf-8")

    # 创建预览（前 N 个字符）
    preview = content[:PREVIEW_CHARS]
    if len(content) > PREVIEW_CHARS:
        preview += "\n... [truncated]"

    placeholder = (
        f"<persisted-output>\n"
        f"Full output saved to: {filepath}\n"
        f"Preview (first {PREVIEW_CHARS} chars):\n"
        f"{preview}\n"
        f"</persisted-output>"
    )

    return placeholder


def tool_result_budget(messages: List[Dict], max_bytes: int = MAX_TOOL_RESULT_BYTES) -> List[Dict]:
    """
    检查工具结果的总大小，超过预算时将最大的结果落盘。

    Args:
        messages: 对话消息列表
        max_bytes: 工具结果总字节数上限

    Returns:
        修改后的消息列表

    Note:
        按大小排序，从最大的开始落盘，直到总大小低于预算
    """
    # 找到所有工具消息
    tool_messages = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool":
            tool_messages.append((i, msg))

    if not tool_messages:
        return messages

    # 计算总大小
    total_size = sum(len(str(msg.get("content", ""))) for _, msg in tool_messages)

    if total_size <= max_bytes:
        return messages

    print(f"[L3 tool_result_budget] Total: {total_size} bytes, budget: {max_bytes}")

    # 按大小排序（从大到小）
    tool_messages_with_size = [
        (i, msg, len(str(msg.get("content", ""))))
        for i, msg in tool_messages
    ]
    tool_messages_with_size.sort(key=lambda x: x[2], reverse=True)

    # 落盘最大的，直到低于预算
    persisted_count = 0
    for idx, msg, size in tool_messages_with_size:
        if total_size <= max_bytes:
            break

        # 只落盘内容 substantial 的
        content = msg.get("content", "")
        if len(str(content)) > 1000:
            # 获取 tool_call_id 用于文件名
            tool_call_id = msg.get("tool_call_id", "unknown")

            # 落盘并替换
            placeholder = _persist_large_output(tool_call_id, str(content))
            msg["content"] = placeholder
            total_size -= size
            total_size += len(placeholder)
            persisted_count += 1

    if persisted_count > 0:
        print(f"[L3 tool_result_budget] Persisted {persisted_count} large results to disk")

    return messages


# =============================================================================
# L4: compact_history — LLM 生成全量摘要
# =============================================================================

COMPACT_SYSTEM_PROMPT = """你是一个对话摘要生成器。你的任务是创建对话的简洁摘要，保留以下信息：

1. 用户当前正在处理的目标/任务
2. 重要发现或结论
3. 已修改或创建的文件
4. 剩余工作或下一步计划
5. 用户提到的任何约束或偏好

只输出摘要。不要调用任何工具。不要提问。
格式化为清晰、可读的摘要。"""


def _estimate_tokens(messages: List[Dict]) -> int:
    """
    估算消息列表的 token 数量。

    Args:
        messages: 对话消息列表

    Returns:
        估算的 token 数

    Note:
        粗略估算：混合内容约 3 字符/token
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("text", "")))
                else:
                    total_chars += len(str(block))

    # 粗略估算：混合内容约 3 字符/token
    return total_chars // 3


def _save_transcript(messages: List[Dict]) -> str:
    """
    保存完整对话到 transcript 文件。

    Args:
        messages: 对话消息列表

    Returns:
        transcript 文件路径
    """
    transcript_dir = Path(".transcripts")
    transcript_dir.mkdir(exist_ok=True)

    timestamp = int(time.time())
    transcript_path = transcript_dir / f"transcript_{timestamp}.jsonl"

    with open(transcript_path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    print(f"[L4 compact_history] Saved transcript to {transcript_path}")
    return str(transcript_path)


def _summarize_history(messages: List[Dict]) -> str:
    """
    使用 LLM 生成对话摘要。

    Args:
        messages: 对话消息列表

    Returns:
        生成的摘要文本
    """
    # 格式化对话用于摘要
    conversation_text = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        if isinstance(content, list):
            # 处理复杂内容
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        text_parts.append(f"[Tool call: {block.get('name', 'unknown')}]")
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[Tool result: {str(block.get('content', ''))[:200]}...]")
                else:
                    text_parts.append(str(block))
            content = "\n".join(text_parts)

        # 截断过长的内容用于摘要
        if len(str(content)) > 2000:
            content = str(content)[:2000] + "... [truncated]"

        conversation_text.append(f"[{role}]: {content}")

    conversation_str = "\n\n".join(conversation_text)

    try:
        response = LLM_CLIENT.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
                {"role": "user", "content": f"请为以下对话生成摘要：\n\n{conversation_str}"}
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"[L4 compact_history] Summarization failed: {e}")
        return f"[Conversation summary unavailable: {e}]"


def compact_history(messages: List[Dict]) -> List[Dict]:
    """
    用 LLM 生成的摘要替换整个对话。

    先保存完整 transcript，再生成摘要。

    Args:
        messages: 对话消息列表

    Returns:
        只包含摘要的新消息列表
    """
    print("[L4 compact_history] Generating conversation summary...")

    # 先保存完整 transcript
    _save_transcript(messages)

    # 生成摘要
    summary = _summarize_history(messages)

    # 用摘要替换消息
    compacted = [{
        "role": "user",
        "content": f"[Compacted conversation history]\n\n{summary}"
    }]

    print(f"[L4 compact_history] Compacted {len(messages)} messages to summary")
    return compacted


# =============================================================================
# 应急压缩: reactive_compact — API 报错时激进裁剪
# =============================================================================

def reactive_compact(messages: List[Dict]) -> List[Dict]:
    """
    API 返回 prompt_too_long 时的应急压缩。

    比 compact_history 更激进：只保留摘要 + 最后 N 条消息。

    Args:
        messages: 对话消息列表

    Returns:
        压缩后的消息列表（摘要 + 尾部消息）
    """
    print("[Emergency reactive_compact] Aggressive trimming...")

    # 保存 transcript
    _save_transcript(messages)

    # 生成摘要
    summary = _summarize_history(messages)

    # 只保留摘要 + 最后 N 条消息
    tail = messages[-REACTIVE_KEEP_TAIL:] if len(messages) > REACTIVE_KEEP_TAIL else []

    result = [{
        "role": "user",
        "content": f"[Reactive compact - emergency trim]\n\n{summary}"
    }] + tail

    print(f"[Emergency reactive_compact] Trimmed to summary + {len(tail)} messages")
    return result


# =============================================================================
# 主压缩管线
# =============================================================================

def apply_compression(messages: List[Dict]) -> List[Dict]:
    """
    在 LLM 调用前应用完整压缩管线。

    执行顺序：budget → snip → micro → (可选) auto
    这个顺序很关键：budget 必须在 micro 之前运行，
    这样大工具结果在被替换为占位符之前会被落盘。

    Args:
        messages: 对话消息列表

    Returns:
        压缩后的消息列表
    """
    # L3: 先落盘大结果
    messages = tool_result_budget(messages)

    # L1: 裁掉中间消息
    messages = snip_compact(messages)

    # L2: 替换旧工具结果
    messages = micro_compact(messages)

    # L4: 检查是否需要自动压缩
    estimated_tokens = _estimate_tokens(messages)
    if estimated_tokens > AUTOCOMPACT_TOKEN_THRESHOLD:
        print(f"[Auto compact] Token estimate: {estimated_tokens} > {AUTOCOMPACT_TOKEN_THRESHOLD}")
        messages = compact_history(messages)

    return messages


# =============================================================================
# Compact 工具 — 供模型主动调用触发压缩
# =============================================================================

def compact_tool() -> str:
    """
    模型可以调用的工具，用于触发压缩。

    Returns:
        状态消息
    """
    return "[Compacted. History summarized.]"


# OpenAI function calling 工具 schema
COMPACT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "compact",
        "description": "当上下文变得很大时压缩对话历史。当你注意到对话变得很长时调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
}
