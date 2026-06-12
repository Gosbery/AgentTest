"""
Filesystem tools: read, write, edit, glob, list_dir.
"""

import glob
from pathlib import Path

from agent.config import WORKDIR


def _safe_path(p: str) -> Path:
    """Ensure path is within WORKDIR."""
    path = (WORKDIR / p).resolve()
    if not str(path).startswith(str(WORKDIR.resolve())):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def list_dir(path: str = ".") -> str:
    try:
        p = _safe_path(path)
        if not p.exists():
            return f"路径不存在: {path}"
        if not p.is_dir():
            return f"不是目录: {path}"
        items = []
        for item in p.iterdir():
            prefix = "[DIR]" if item.is_dir() else "[FILE]"
            items.append(f"{prefix} {item.name}")
        return "\n".join(items) if items else "空目录"
    except Exception as e:
        return f"list_dir error: {e}"


def read_file(path: str, limit: int = None) -> str:
    try:
        lines = _safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"read_file error: {e}"


def write_file(path: str, content: str) -> str:
    try:
        file_path = _safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"write_file error: {e}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = _safe_path(path)
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"
    except Exception as e:
        return f"edit_file error: {e}"


def glob_files(pattern: str) -> str:
    try:
        results = []
        for match in glob.glob(str(WORKDIR / pattern)):
            match_path = Path(match)
            try:
                match_path.resolve().relative_to(WORKDIR.resolve())
                results.append(str(match_path.relative_to(WORKDIR)))
            except ValueError:
                continue
        return "\n".join(results) if results else f"没有匹配到文件: {pattern}"
    except Exception as e:
        return f"glob_files error: {e}"
