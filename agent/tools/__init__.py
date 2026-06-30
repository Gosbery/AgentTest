"""
Tool registry — aggregates all tool functions and their OpenAI-compatible schemas.
"""

from agent.tools.filesystem import read_file, write_file, edit_file, glob_files, list_dir
from agent.tools.shell import run_bash
from agent.tools.todo import run_todo_write
from agent.tools.task_system import (
    create_task, list_tasks, get_task, claim_task, complete_task
)
from agent.tools.cron_scheduler import schedule_job, cancel_job, list_jobs
from agent.tools.agent_teams import (
    spawn_teammate_thread,
    run_send_message,
    run_check_inbox,
)


# Function registry: name -> callable
TOOLS = {
    "list_dir": list_dir,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "glob_files": glob_files,
    "run_bash": run_bash,
    "todo_write": run_todo_write,
    "create_task": create_task,
    "list_tasks": list_tasks,
    "get_task": get_task,
    "claim_task": claim_task,
    "complete_task": complete_task,
    "schedule_cron": schedule_job,
    "list_crons": list_jobs,
    "cancel_cron": cancel_job,
    "spawn_teammate": spawn_teammate_thread,
    "send_message": run_send_message,
    "check_inbox": run_check_inbox,
}


# OpenAI-compatible function calling schemas
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出指定目录下的文件和文件夹",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"}
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
                    "path": {"type": "string", "description": "文件路径"},
                    "limit": {"type": "integer", "description": "最大返回行数"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "向指定文件写入内容。文件不存在则创建，存在则覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目标文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "编辑文件。用 new_text 替换 old_text（仅替换第一次出现）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_text": {"type": "string", "description": "要替换的旧文本"},
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
            "description": "根据 glob pattern 搜索文件",
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
            "name": "run_bash",
            "description": "执行 shell 命令并返回输出",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的命令"},
                    "run_in_background": {
                        "type": "boolean",
                        "description": "If true, run the command in background and continue processing other tasks. Use for slow operations like install, build, test.",
                    },
                },
                "required": ["command"],
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
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new persistent task with optional dependencies. Tasks are saved to .tasks/ directory and persist across sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Short title of the task"},
                    "description": {"type": "string", "description": "Detailed description of the task"},
                    "blockedBy": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of task IDs that must be completed before this task can start"
                    },
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List all tasks with their current status, owner, and dependencies.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_task",
            "description": "Get full details of a specific task including description and dependencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "The task ID to retrieve"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "claim_task",
            "description": "Claim a task to start working on it. Sets owner and changes status to in_progress. Fails if dependencies are not met.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "The task ID to claim"},
                    "owner": {"type": "string", "description": "Name of the agent claiming the task", "default": "agent"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_task",
            "description": "Mark a task as completed and unlock any downstream tasks that were blocked by it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "The task ID to complete"},
                },
                "required": ["task_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_cron",
            "description": "Schedule a recurring or one-shot cron job. The prompt will be injected to the agent when the cron expression matches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cron": {
                        "type": "string",
                        "description": "5-field cron expression: minute hour day month weekday (e.g. '0 9 * * *' for daily 9am)",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The message to inject to the agent when triggered",
                    },
                    "recurring": {
                        "type": "boolean",
                        "description": "True for recurring, False for one-shot (default True)",
                    },
                    "durable": {
                        "type": "boolean",
                        "description": "True to persist across restarts (default True)",
                    },
                },
                "required": ["cron", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_crons",
            "description": "List all scheduled cron jobs with their status.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_cron",
            "description": "Cancel a scheduled cron job by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "The cron job ID to cancel"},
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_teammate",
            "description": "Spawn a teammate agent to work on a task in parallel. The teammate runs in its own thread with simplified tools (bash, read, write, send_message).",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Unique name for the teammate (e.g., 'alice', 'bob')"},
                    "role": {"type": "string", "description": "Role description (e.g., 'backend developer', 'tester')"},
                    "prompt": {"type": "string", "description": "Task description for the teammate"},
                },
                "required": ["name", "role", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Send a message to another agent (teammate or lead).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_agent": {"type": "string", "description": "Recipient agent name (e.g., 'alice', 'lead')"},
                    "content": {"type": "string", "description": "Message content"},
                },
                "required": ["to_agent", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_inbox",
            "description": "Check your inbox for messages from teammates. Messages are consumed (deleted) after reading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string", "description": "Agent name to check inbox for (usually 'lead')"},
                },
                "required": ["agent"],
            },
        },
    },
]


def make_tool_schema(name, description, properties, required):
    """Helper to create OpenAI-compatible tool schemas."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    }
