# tools.py
from pathlib import Path
import glob


# 全局 TODO 状态（进程内存，退出后清空）
CURRENT_TODOS: list[dict] = []


def list_dir(path: str = ".") -> str:
    try:
        p = Path(path)
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


def read_file(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"文件不存在: {path}"
        if not p.is_file():
            return f"不是文件: {path}"

        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"read_file error: {e}"


def write_file(path: str, content: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"写入成功: {path}"
    except Exception as e:
        return f"write_file error: {e}"


def edit_file(path: str, old_text: str, new_text: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"文件不存在: {path}"
        if not p.is_file():
            return f"不是文件: {path}"

        content = p.read_text(encoding="utf-8")

        if old_text not in content:
            return f"未找到要替换的内容: {old_text}"

        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")

        return f"编辑成功: {path}"
    except Exception as e:
        return f"edit_file error: {e}"


def glob_files(pattern: str) -> str:
    try:
        matches = glob.glob(pattern, recursive=True)

        if not matches:
            return f"没有匹配到文件: {pattern}"

        return "\n".join(matches)
    except Exception as e:
        return f"glob_files error: {e}"


def get_location() -> str:
    return "Los Angeles, California, USA"


def get_weather(location: str) -> str:
    fake_weather_data = {
        "Los Angeles, California, USA": "晴，气温 26°C，湿度 45%，微风。",
        "Toronto, Ontario, Canada": "多云，气温 18°C，湿度 60%，有小风。",
        "Shanghai, China": "小雨，气温 24°C，湿度 78%。",
    }

    return fake_weather_data.get(
        location,
        f"{location} 的天气：晴，气温 25°C，湿度 50%。"
    )


def run_todo_write(todos: list) -> str:
    """
    创建和管理任务列表。
    
    输入：
        todos: list[dict]
            每个 dict 包含 content 和 status 字段。
            status 可选值: pending, in_progress, completed
    
    输出：
        str
            更新摘要。
    """
    global CURRENT_TODOS
    CURRENT_TODOS = todos

    lines = ["\n## Current Tasks"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": ">", "completed": "[x]"}[t.get("status", "pending")]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"


TOOLS = {
    "list_dir": list_dir,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob_files": glob_files,
    "get_location": get_location,
    "get_weather": get_weather,
    "todo_write": run_todo_write,
}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出指定目录下的文件和文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，例如 . 或 ./src"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文件的完整内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径，例如 ./main.py"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "向指定文件写入内容。如果文件不存在则创建，如果存在则覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件路径"},
                    "content": {"type": "string", "description": "要写入的完整内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "编辑文件内容。用 new_text 替换文件中的 old_text，只替换第一次出现的位置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要编辑的文件路径"},
                    "old_text": {"type": "string", "description": "需要被替换的旧文本"},
                    "new_text": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_files",
            "description": "根据 glob pattern 搜索文件，例如 *.py、**/*.py",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 搜索模式"}
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": "获取用户当前所在位置。此工具是模拟定位。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "根据位置查询天气。此工具是模拟天气查询。",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市或地区名称"}
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "Create and manage a task list. Use this to plan complex tasks before executing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"]
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        },
    },
]