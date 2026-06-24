"""
Memory consolidator — 记忆整理和去重。

整理时机：
    当记忆文件数达到阈值（默认 10）时触发。
    教学版简化为文件数阈值，真实 CC 有四层门控。

整理流程：
    1. 列出所有记忆文件
    2. 检查是否达到阈值
    3. 调用 LLM 去重、合并矛盾、淘汰过时记忆
    4. 用整理后的结果替换所有文件
    5. 重建索引

CC 真实实现（autoDream.ts）有四层门控：
    1. 时间门控：距上次合并 >= 24 小时
    2. 扫描节流：避免频繁扫描文件系统
    3. 会话门控：自上次合并以来修改了 >= 5 个会话 transcript
    4. 锁门控：没有其他进程正在合并

教学版简化为单一阈值。
"""

import json
import re
from pathlib import Path
from typing import List, Dict

from agent.config import LLM_CLIENT, MODEL_ID
from agent.memory.storage import (
    MEMORY_DIR,
    list_memory_files,
    write_memory_file,
    rebuild_index,
)

# 触发整理的文件数阈值
CONSOLIDATE_THRESHOLD = 10


def consolidate_memories() -> int:
    """
    整理记忆文件：去重、合并矛盾、淘汰过时记忆。

    当文件数达到阈值时触发。

    Returns:
        整理后剩余的记忆数量，如果未达到阈值则返回 -1

    Example:
        >>> remaining = consolidate_memories()
        >>> if remaining >= 0:
        ...     print(f"Consolidated to {remaining} memories")
    """
    files = list_memory_files()

    if len(files) < CONSOLIDATE_THRESHOLD:
        return -1  # 太少，不值得整理

    print(f"[Memory consolidate] {len(files)} memories >= threshold {CONSOLIDATE_THRESHOLD}, consolidating...")

    # 构建所有记忆的清单
    memories_text = []
    for f in files:
        filepath = MEMORY_DIR / f["filename"]
        try:
            content = filepath.read_text(encoding="utf-8")
            memories_text.append(f"=== {f['filename']} ===\n{content}")
        except Exception as e:
            print(f"[Memory consolidate] Error reading {f['filename']}: {e}")
            continue

    if not memories_text:
        return 0

    all_memories = "\n\n".join(memories_text)

    # 构建整理 prompt
    prompt = f"""You are a memory consolidator. Review the following memories and:
1. Remove duplicates (same information stated differently)
2. Merge related memories into a single, better memory
3. Remove outdated or contradictory memories (keep the most recent/accurate)
4. Keep only memories that are still useful

Return a JSON array of the consolidated memories with: name, type, description, body.
If a memory should be removed, don't include it in the output.

Memories to consolidate:
{all_memories}
"""

    try:
        # 调用 LLM 整理
        response = LLM_CLIENT.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.0,
        )

        response_text = response.choices[0].message.content.strip()

        # 解析 JSON 数组
        consolidated = _parse_consolidated(response_text)

        if not consolidated:
            print("[Memory consolidate] No consolidated memories returned")
            return len(files)

        # 删除所有旧文件
        _clear_memory_files()

        # 写入整理后的记忆
        for mem in consolidated:
            try:
                write_memory_file(
                    name=mem.get("name", "unnamed"),
                    mem_type=mem.get("type", "project"),
                    description=mem.get("description", ""),
                    body=mem.get("body", ""),
                )
            except Exception as e:
                print(f"[Memory consolidate] Failed to write: {e}")

        print(f"[Memory consolidate] Consolidated {len(files)} -> {len(consolidated)} memories")
        return len(consolidated)

    except Exception as e:
        print(f"[Memory consolidate] Consolidation failed: {e}")
        return len(files)


def _parse_consolidated(text: str) -> List[Dict]:
    """
    从 LLM 响应中解析整理后的记忆数组。

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

    print(f"[Memory consolidate] Failed to parse response: {text[:200]}")
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


def _clear_memory_files() -> None:
    """
    删除所有记忆文件（保留目录）。
    """
    if not MEMORY_DIR.exists():
        return

    for filepath in MEMORY_DIR.glob("*.md"):
        try:
            filepath.unlink()
        except Exception as e:
            print(f"[Memory consolidate] Failed to delete {filepath}: {e}")

    print("[Memory consolidate] Cleared all memory files")
