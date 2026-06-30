"""
Agent Teams — 多 Agent 协作系统。

s15 新增：
  - MessageBus: 文件收件箱系统，每个 Agent 有 .jsonl 邮箱
  - spawn_teammate_thread: 启动队友线程，在自己的 daemon 线程里运行
  - send_message / check_inbox: 通信工具
  - inbox 注入: Lead 接收队友消息并注入 history
"""

import json
import time
import threading
from pathlib import Path

from agent.config import WORKDIR, LLM_CLIENT, MODEL_ID
from agent.tools.shell import run_bash
from agent.tools.filesystem import read_file, write_file

# ── 配置 ──
MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_DIR.mkdir(exist_ok=True)

# 队友线程限制（教学版）
MAX_TEAMMATE_ROUNDS = 10

# ── 状态 ──
active_teammates: dict[str, dict] = {}  # name -> {thread, role, status}
teammate_lock = threading.Lock()


# ── MessageBus: 文件收件箱 ──
class MessageBus:
    """
    基于文件的异步消息总线。
    
    每个 Agent 有一个 .jsonl 邮箱文件。
    发消息 = 往对方的文件里 append 一行 JSON。
    读消息 = 读文件 + 删除（消费式）。
    """
    
    def send(self, from_agent: str, to_agent: str,
             content: str, msg_type: str = "message") -> None:
        """
        发送消息到指定 Agent 的收件箱。
        
        Args:
            from_agent: 发送者名称
            to_agent: 接收者名称
            content: 消息内容
            msg_type: 消息类型（message/result/idle_notification 等）
        """
        msg = {
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "type": msg_type,
            "ts": time.time(),
        }
        inbox = MAILBOX_DIR / f"{to_agent}.jsonl"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        print(f"[MessageBus] {from_agent} -> {to_agent}: {content[:50]}...")
    
    def read_inbox(self, agent: str) -> list[dict]:
        """
        读取指定 Agent 的收件箱（消费式：读完删除）。
        
        Args:
            agent: Agent 名称
            
        Returns:
            消息列表，每条消息是 dict
        """
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if not inbox.exists():
            return []
        
        try:
            lines = inbox.read_text(encoding="utf-8").splitlines()
            msgs = [json.loads(line) for line in lines if line.strip()]
            inbox.unlink()  # 消费式：读完删除
            return msgs
        except Exception as e:
            print(f"[MessageBus] Error reading inbox for {agent}: {e}")
            return []


# 全局 MessageBus 实例
BUS = MessageBus()


# ── 队友工具函数 ──
def run_send_message(to_agent: str, content: str, from_agent: str = "lead") -> str:
    """
    发送消息给另一个 Agent。
    
    Args:
        to_agent: 接收者名称
        content: 消息内容
        from_agent: 发送者名称（默认为 "lead"，队友调用时会自动覆盖）
        
    Returns:
        确认信息
    """
    BUS.send(from_agent, to_agent, content)
    return f"Message sent to {to_agent}"


def make_send_message_for_teammate(teammate_name: str):
    """
    为队友创建专属的 send_message 函数，自动设置 from_agent。
    
    Args:
        teammate_name: 队友名称
        
    Returns:
        绑定了 from_agent 的 send_message 函数
    """
    def teammate_send_message(to_agent: str, content: str) -> str:
        BUS.send(teammate_name, to_agent, content)
        return f"Message sent to {to_agent}"
    return teammate_send_message


def run_check_inbox(agent: str) -> str:
    """
    检查指定 Agent 的收件箱。
    
    Args:
        agent: Agent 名称
        
    Returns:
        收件箱内容（JSON 格式）或 "No messages"
    """
    messages = BUS.read_inbox(agent)
    if not messages:
        return "No messages"
    
    # 格式化输出
    lines = []
    for msg in messages:
        lines.append(f"From {msg['from']}: {msg['content']}")
    return "\n".join(lines)


# ── 队友线程 ──
def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    """
    启动一个队友线程。队友在自己的 daemon 线程里运行，有自己的 system prompt、
    messages、简化工具集（bash、read、write、send_message）。
    
    Args:
        name: 队友名称（唯一标识）
        role: 队友角色描述（如 "backend developer"）
        prompt: 初始任务描述
        
    Returns:
        确认信息
    """
    with teammate_lock:
        if name in active_teammates:
            return f"Teammate '{name}' already exists"
        active_teammates[name] = {
            "thread": None,
            "role": role,
            "status": "starting",
        }
    
    system = f"You are '{name}', a {role}. Use tools to complete tasks. When done, send a summary to 'lead'."
    
    def run():
        """队友线程的主逻辑。"""
        messages = [{"role": "user", "content": prompt}]
        
        # 队友的简化工具集
        sub_tools = [
            {
                "type": "function",
                "function": {
                    "name": "run_bash",
                    "description": "Execute a shell command",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "send_message",
                    "description": "Send a message to another agent",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "to_agent": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["to_agent", "content"],
                    },
                },
            },
        ]
        
        # 工具函数映射（队友专属）
        teammate_send = make_send_message_for_teammate(name)
        tool_funcs = {
            "run_bash": run_bash,
            "read_file": read_file,
            "write_file": write_file,
            "send_message": teammate_send,
        }
        
        summary = ""
        
        for round_idx in range(MAX_TEAMMATE_ROUNDS):
            print(f"[Teammate {name}] Round {round_idx + 1}/{MAX_TEAMMATE_ROUNDS}")
            
            # 检查收件箱
            inbox = BUS.read_inbox(name)
            if inbox:
                inbox_text = "\n".join(
                    f"From {m['from']}: {m['content']}" for m in inbox
                )
                messages.append({
                    "role": "user",
                    "content": f"<inbox>\n{inbox_text}\n</inbox>",
                })
            
            # LLM 调用
            try:
                response = LLM_CLIENT.chat.completions.create(
                    model=MODEL_ID,
                    messages=messages[-20:],  # 限制上下文
                    system=system,
                    tools=sub_tools,
                    max_tokens=8000,
                )
                message = response.choices[0].message
            except Exception as e:
                print(f"[Teammate {name}] LLM error: {e}")
                summary = f"Error: {e}"
                break
            
            # 处理响应
            messages.append({"role": "assistant", "content": message.content or ""})
            
            # 没有工具调用 -> 完成
            if not message.tool_calls:
                summary = message.content or "(no response)"
                break
            
            # 执行工具
            for tc in message.tool_calls:
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                
                print(f"[Teammate {name}] Tool: {tool_name}({args})")
                
                tool_func = tool_funcs.get(tool_name)
                if tool_func:
                    try:
                        result = tool_func(**args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(result),
                        })
                    except Exception as e:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"Error: {e}",
                        })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"Unknown tool: {tool_name}",
                    })
        
        # 完成后发送 summary 给 Lead
        if not summary:
            summary = "Completed (no final message)"
        
        BUS.send(name, "lead", summary, "result")
        print(f"[Teammate {name}] Finished: {summary[:100]}...")
        
        with teammate_lock:
            active_teammates[name]["status"] = "completed"
    
    # 启动线程
    thread = threading.Thread(target=run, daemon=True)
    with teammate_lock:
        active_teammates[name]["thread"] = thread
        active_teammates[name]["status"] = "running"
    
    thread.start()
    return f"Teammate '{name}' ({role}) started"


# ── Lead 的 inbox 注入 ──
def collect_teammate_messages() -> list[str]:
    """
    收集 Lead 收件箱中的队友消息，格式化为 <inbox> 标签。
    
    Returns:
        格式化后的消息列表
    """
    messages = BUS.read_inbox("lead")
    if not messages:
        return []
    
    notifications = []
    for msg in messages:
        msg_type = msg.get("type", "message")
        from_agent = msg.get("from", "unknown")
        content = msg.get("content", "")
        
        if msg_type == "result":
            notifications.append(
                f"<teammate_result>\n"
                f"  <from>{from_agent}</from>\n"
                f"  <summary>{content}</summary>\n"
                f"</teammate_result>"
            )
        else:
            notifications.append(
                f"<teammate_message>\n"
                f"  <from>{from_agent}</from>\n"
                f"  <content>{content}</content>\n"
                f"</teammate_message>"
            )
    
    return notifications
