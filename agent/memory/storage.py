"""
Memory storage — 记忆文件存储和索引管理。

存储结构：
    .memory/
        MEMORY.md          # 索引文件，一行一个链接
        user-preference-tabs.md
        project-auth-rewrite.md
        ...

每个记忆文件格式：
    ---
    name: user-preference-tabs
    description: User prefers tabs for indentation
    type: user
    ---

    User prefers using tabs, not spaces, for indentation.
    **Why:** Consistency with existing codebase conventions.
    **How to apply:** Always use tabs when writing or editing files.

四类记忆：
    - user:      用户偏好（你是谁）
    - feedback:  做事方式（怎么做事）
    - project:   项目背景（正在发生什么）
    - reference: 入口线索（东西在哪找）
"""

import re
from pathlib import Path
from typing import List, Dict, Optional

# 记忆存储目录
MEMORY_DIR = Path(".memory")


def _ensure_memory_dir() -> Path:
    """确保记忆目录存在。"""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR


def _slugify(name: str) -> str:
    """将名称转换为文件名安全的 slug。"""
    return name.lower().replace(" ", "-").replace("_", "-")


def write_memory_file(
    name: str,
    mem_type: str,
    description: str,
    body: str,
) -> str:
    """
    写入一个记忆文件并重建索引。

    Args:
        name: 记忆名称（如 "user-preference-tabs"）
        mem_type: 记忆类型（user/feedback/project/reference）
        description: 简短描述
        body: 记忆正文

    Returns:
        写入的文件路径

    Example:
        >>> write_memory_file(
        ...     "user-preference-tabs",
        ...     "user",
        ...     "User prefers tabs for indentation",
        ...     "User prefers using tabs, not spaces, for indentation."
        ... )
    """
    _ensure_memory_dir()

    slug = _slugify(name)
    filepath = MEMORY_DIR / f"{slug}.md"

    # 构建文件内容
    content = f"""---
name: {name}
description: {description}
type: {mem_type}
---

{body}
"""

    filepath.write_text(content, encoding="utf-8")
    print(f"[Memory] Wrote: {filepath}")

    # 重建索引
    rebuild_index()

    return str(filepath)


def list_memory_files() -> List[Dict[str, str]]:
    """
    列出所有记忆文件及其元数据。

    Returns:
        记忆文件列表，每个元素包含 filename, name, description, type

    Example:
        >>> files = list_memory_files()
        >>> for f in files:
        ...     print(f"{f['name']}: {f['description']}")
    """
    if not MEMORY_DIR.exists():
        return []

    files = []
    for filepath in MEMORY_DIR.glob("*.md"):
        if filepath.name == "MEMORY.md":
            continue  # 跳过索引文件

        # 读取文件并解析 frontmatter
        try:
            content = filepath.read_text(encoding="utf-8")
            metadata = _parse_frontmatter(content)

            files.append({
                "filename": filepath.name,
                "name": metadata.get("name", filepath.stem),
                "description": metadata.get("description", ""),
                "type": metadata.get("type", "unknown"),
            })
        except Exception as e:
            print(f"[Memory] Error reading {filepath}: {e}")
            continue

    # 按修改时间降序排序（最新的在前）
    files.sort(
        key=lambda f: (MEMORY_DIR / f["filename"]).stat().st_mtime,
        reverse=True,
    )

    return files


def _parse_frontmatter(content: str) -> Dict[str, str]:
    """
    解析 YAML frontmatter。

    Args:
        content: 文件内容

    Returns:
        元数据字典
    """
    metadata = {}

    # 匹配 --- ... --- 块
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return metadata

    frontmatter = match.group(1)

    # 简单解析 key: value 格式
    for line in frontmatter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()

    return metadata


def rebuild_index() -> str:
    """
    重建 MEMORY.md 索引文件。

    Returns:
        索引文件路径
    """
    _ensure_memory_dir()

    files = list_memory_files()
    index_path = MEMORY_DIR / "MEMORY.md"

    if not files:
        # 没有记忆文件时清空索引
        index_path.write_text("# Memory Index\n\nNo memories yet.\n", encoding="utf-8")
        return str(index_path)

    # 构建索引内容
    lines = ["# Memory Index\n"]
    for f in files:
        lines.append(f"- [{f['name']}]({f['filename']}) — {f['description']}")

    index_content = "\n".join(lines) + "\n"
    index_path.write_text(index_content, encoding="utf-8")

    print(f"[Memory] Rebuilt index with {len(files)} memories")
    return str(index_path)


def get_memory_index() -> str:
    """
    获取记忆索引内容，用于注入 system prompt。

    Returns:
        索引文本，如果没有记忆则返回空字符串
    """
    index_path = MEMORY_DIR / "MEMORY.md"
    if not index_path.exists():
        return ""

    try:
        return index_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[Memory] Error reading index: {e}")
        return ""


def read_memory_file(filename: str) -> Optional[str]:
    """
    读取指定记忆文件的完整内容。

    Args:
        filename: 文件名（如 "user-preference-tabs.md"）

    Returns:
        文件内容，如果文件不存在则返回 None
    """
    filepath = MEMORY_DIR / filename
    if not filepath.exists():
        return None

    try:
        return filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[Memory] Error reading {filename}: {e}")
        return None
