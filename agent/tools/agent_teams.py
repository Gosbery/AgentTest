"""
Agent Teams — 多 Agent 协作系统。

s15 新增：
  - MessageBus: 文件收件箱系统，每个 Agent 有 .jsonl 邮箱
  - spawn_teammate_thread: 启动队友线程，在自己的 daemon 线程里运行
  - send_message / check_inbox: 通信工具
  - inbox 注入: Lead 接收队友消息并注入 history

s16 新增：
  - ProtocolState: 请求状态追踪（pending → approved / rejected）
  - dispatch_message: 按消息类型路由到处理器
  - match_response: 通过 request_id 关联回复与请求，含类型校验
  - consume_lead_inbox: 统一 inbox 消费，先路由协议消息
  - request_shutdown / submit_plan / review_plan: 协议工具
  - 队友 idle loop: 完成后等待而不是退出

s17 新增：
  - idle_poll: 空闲轮询（每5s检查inbox + 任务板）
  - scan_unclaimed_tasks: 扫描可认领任务（pending + 无owner + 依赖已完成）
  - 队友自动认领任务，不依赖Lead手动分配
  - 队友工具 +3: list_tasks, claim_task, complete_task
  - 身份重注入: autoCompact后重新注入身份信息
  - 三阶段生命周期: WORK → IDLE → SHUTDOWN
"""

import json
import time
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

from agent.config import WORKDIR, LLM_CLIENT, MODEL_ID
from agent.tools.shell import run_bash
from agent.tools.filesystem import read_file, write_file
from agent.tools.task_system import (
    list_all_tasks, load_task, save_task, can_start, _task_path
)

# ── 配置 ──
MAILBOX_DIR = WORKDIR / ".mailboxes"
MAILBOX_DIR.mkdir(exist_ok=True)

# 队友线程限制（教学版）
MAX_TEAMMATE_ROUNDS = 10

# s17: idle 轮询配置
IDLE_POLL_INTERVAL = 5   # seconds
IDLE_TIMEOUT = 60        # seconds

# ── 状态 ──
active_teammates: dict[str, dict] = {}  # name -> {thread, role, status}
teammate_lock = threading.Lock()


# ── s16: ProtocolState — 请求状态追踪 ──
@dataclass
class ProtocolState:
    """协议请求的状态记录。"""
    request_id: str      # 唯一 ID，如 "req_004281"
    type: str            # "shutdown" | "plan_approval"
    sender: str          # 发起方
    target: str          # 接收方
    status: str          # pending | approved | rejected
    payload: str         # 计划文本或关机原因
    created_at: float    # 时间戳


pending_requests: dict[str, ProtocolState] = {}
protocol_lock = threading.Lock()

_req_counter = 0


def new_request_id() -> str:
    """生成唯一的请求 ID。"""
    global _req_counter
    _req_counter += 1
    return f"req_{_req_counter:06d}"


def match_response(response_type: str, request_id: str, approve: bool) -> None:
    """
    通过 request_id 关联回复与请求，含类型校验。
    
    Args:
        response_type: 响应消息类型（如 "shutdown_response"）
        request_id: 请求 ID
        approve: 是否批准
    """
    with protocol_lock:
        state = pending_requests.get(request_id)
        if not state:
            print(f"[Protocol] No pending request found for {request_id}")
            return
        
        # 类型校验：shutdown 请求只能匹配 shutdown 响应
        expected_response = f"{state.type}_response"
        if response_type != expected_response:
            print(f"[Protocol] Type mismatch: expected {expected_response}, got {response_type}")
            return
        
        # 已处理，跳过重复
        if state.status != "pending":
            print(f"[Protocol] Request {request_id} already resolved: {state.status}")
            return
        
        state.status = "approved" if approve else "rejected"
        print(f"[Protocol] Request {request_id} ({state.type}) => {state.status}")


# ── MessageBus: 文件收件箱 ──
class MessageBus:
    """
    基于文件的异步消息总线。
    
    每个 Agent 有一个 .jsonl 邮箱文件。
    发消息 = 往对方的文件里 append 一行 JSON。
    读消息 = 读文件 + 删除（消费式）。
    """
    
    def send(self, from_agent: str, to_agent: str,
             content: str, msg_type: str = "message",
             metadata: dict = None) -> None:
        """
        发送消息到指定 Agent 的收件箱。
        
        Args:
            from_agent: 发送者名称
            to_agent: 接收者名称
            content: 消息内容
            msg_type: 消息类型（message/result/shutdown_request 等）
            metadata: 附加元数据（如 request_id, approve 等）
        """
        msg = {
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "type": msg_type,
            "ts": time.time(),
        }
        if metadata:
            msg["metadata"] = metadata
        inbox = MAILBOX_DIR / f"{to_agent}.jsonl"
        with open(inbox, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        print(f"[MessageBus] {from_agent} -> {to_agent} ({msg_type}): {content[:50]}...")
    
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


# ── s16: consume_lead_inbox — 统一 inbox 消费 ──
def consume_lead_inbox() -> list[dict]:
    """
    统一消费 Lead 的收件箱。先路由协议消息（更新 pending_requests 状态），
    再返回所有消息供格式化注入。
    
    check_inbox 工具和主循环末尾都调用此函数，避免消息被读走但协议状态没更新。
    
    Returns:
        原始消息列表
    """
    msgs = BUS.read_inbox("lead")
    for msg in msgs:
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")
        msg_type = msg.get("type", "")
        # 协议响应消息：自动路由到 match_response
        if req_id and msg_type.endswith("_response"):
            match_response(msg_type, req_id, meta.get("approve", False))
    return msgs


# ── s17: scan_unclaimed_tasks — 扫描可认领任务 ──
def scan_unclaimed_tasks() -> list[dict]:
    """
    扫描任务看板，找出可认领的任务。
    
    条件：
    - status == "pending"
    - owner 为空
    - can_start() 返回 True（所有依赖已完成）
    
    Returns:
        可认领的任务列表（按文件名排序）
    """
    unclaimed = []
    tasks_dir = WORKDIR / ".tasks"
    if not tasks_dir.exists():
        return []
    
    for f in sorted(tasks_dir.glob("task_*.json")):
        try:
            task_data = json.loads(f.read_text(encoding="utf-8"))
            if (task_data.get("status") == "pending"
                    and not task_data.get("owner")
                    and can_start(task_data["id"])):
                unclaimed.append(task_data)
        except Exception as e:
            print(f"[scan_unclaimed_tasks] Error reading {f}: {e}")
    return unclaimed


# ── s17: idle_poll — 空闲轮询 ──
def idle_poll(name: str, messages: list, role: str) -> str:
    """
    空闲时轮询 inbox 和任务看板。
    
    优先检查 inbox（可能包含 shutdown_request），
    其次扫描任务看板寻找可认领任务。
    
    Args:
        name: 队友名称
        messages: 队友的 messages 列表
        role: 队友角色
        
    Returns:
        "work" - 找到新任务，回到 WORK 阶段
        "shutdown" - 收到关机请求
        "timeout" - 超时退出
    """
    for _ in range(IDLE_TIMEOUT // IDLE_POLL_INTERVAL):
        time.sleep(IDLE_POLL_INTERVAL)
        
        # ① 检查收件箱（优先）
        inbox = BUS.read_inbox(name)
        if inbox:
            # shutdown_request 立即处理
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    meta = msg.get("metadata", {})
                    req_id = meta.get("request_id", "")
                    # 回复 shutdown_response
                    BUS.send(name, "lead", "Shutting down.",
                             "shutdown_response",
                             {"request_id": req_id, "approve": True})
                    print(f"[Teammate {name}] Received shutdown request in idle, responding and exiting")
                    return "shutdown"
            
            # 普通消息注入上下文，回到 WORK
            for msg in inbox:
                messages.append({
                    "role": "user",
                    "content": f"<inbox>From {msg['from']}: {msg['content']}</inbox>",
                })
            print(f"[Teammate {name}] Received new message in idle, resuming work")
            return "work"
        
        # ② 扫描任务看板
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            task = unclaimed[0]
            # 尝试认领
            try:
                task_obj = load_task(task["id"])
                if task_obj.status != "pending":
                    continue
                if task_obj.owner:
                    continue
                if not can_start(task["id"]):
                    continue
                
                task_obj.owner = name
                task_obj.status = "in_progress"
                save_task(task_obj)
                
                # 注入任务信息到 messages
                messages.append({
                    "role": "user",
                    "content": f"<auto_claimed_task>You auto-claimed task {task['id']}: {task['subject']}. "
                               f"Description: {task.get('description', 'No description')}. "
                               f"Complete this task and use complete_task to mark it done.</auto_claimed_task>",
                })
                print(f"[Teammate {name}] Auto-claimed task {task['id']}: {task['subject']}")
                return "work"
            except Exception as e:
                print(f"[Teammate {name}] Error claiming task: {e}")
                continue
    
    print(f"[Teammate {name}] Idle timeout ({IDLE_TIMEOUT}s), shutting down")
    return "timeout"


# ── 队友工具函数 ──
def run_send_message(to_agent: str, content: str) -> str:
    """Lead 发送消息给队友（from_agent 自动为 "lead"）。"""
    BUS.send("lead", to_agent, content)
    return f"Message sent to {to_agent}"


def make_send_message_for_teammate(teammate_name: str):
    """为队友创建专属的 send_message 函数，自动设置 from_agent。"""
    def teammate_send_message(to_agent: str, content: str) -> str:
        BUS.send(teammate_name, to_agent, content)
        return f"Message sent to {to_agent}"
    return teammate_send_message


def run_check_inbox(agent: str = "lead") -> str:
    """
    检查收件箱（统一走 consume_lead_inbox 路由协议消息）。
    """
    if agent == "lead":
        messages = consume_lead_inbox()
    else:
        messages = BUS.read_inbox(agent)
    if not messages:
        return "No messages"
    lines = []
    for msg in messages:
        lines.append(f"From {msg['from']} ({msg.get('type', 'message')}): {msg['content']}")
    return "\n".join(lines)


# ── s16: 协议工具 ──
def run_request_shutdown(teammate: str) -> str:
    """
    Lead 请求队友关机。创建 ProtocolState，发送 shutdown_request。
    """
    req_id = new_request_id()
    with protocol_lock:
        pending_requests[req_id] = ProtocolState(
            request_id=req_id,
            type="shutdown",
            sender="lead",
            target=teammate,
            status="pending",
            payload="Lead requested shutdown",
            created_at=time.time(),
        )
    BUS.send("lead", teammate, "Please shut down gracefully.",
             "shutdown_request", {"request_id": req_id})
    return f"Shutdown request sent to '{teammate}' (id={req_id})"


def run_review_plan(request_id: str, approve: bool, feedback: str = "") -> str:
    """
    Lead 审批队友提交的计划。通过 request_id 找到计划审批请求，发送响应。
    """
    with protocol_lock:
        state = pending_requests.get(request_id)
    if not state:
        return f"No pending plan approval found for {request_id}"
    if state.type != "plan_approval":
        return f"Request {request_id} is type '{state.type}', not 'plan_approval'"
    if state.status != "pending":
        return f"Request {request_id} already resolved: {state.status}"

    response_content = feedback if feedback else ("Plan approved." if approve else "Plan rejected.")
    BUS.send("lead", state.sender, response_content,
             "plan_approval_response",
             {"request_id": request_id, "approve": approve})
    # 立即更新本地状态（不依赖队友回传）
    with protocol_lock:
        state.status = "approved" if approve else "rejected"
    action = "approved" if approve else "rejected"
    return f"Plan {action} for request {request_id}"


def make_submit_plan_for_teammate(teammate_name: str):
    """为队友创建专属的 submit_plan 函数。"""
    def submit_plan(plan: str) -> str:
        req_id = new_request_id()
        with protocol_lock:
            pending_requests[req_id] = ProtocolState(
                request_id=req_id,
                type="plan_approval",
                sender=teammate_name,
                target="lead",
                status="pending",
                payload=plan,
                created_at=time.time(),
            )
        BUS.send(teammate_name, "lead", plan,
                 "plan_approval_request", {"request_id": req_id})
        return f"Plan submitted for review (id={req_id}). Wait for lead's response."
    return submit_plan


# ── s16: dispatch_message — 队友按消息类型路由 ──
def handle_inbox_message(name: str, msg: dict, messages: list) -> bool:
    """
    队友处理收件箱消息。按消息类型分发：
    - shutdown_request → 回复 shutdown_response，返回 True（停止循环）
    - plan_approval_response → 注入审批结果到 messages
    - 普通消息 → 注入到 messages
    
    Args:
        name: 队友名称
        msg: 消息 dict
        messages: 队友的 messages 列表
        
    Returns:
        True 表示应该停止循环（收到关机请求）
    """
    msg_type = msg.get("type", "message")
    meta = msg.get("metadata", {})
    req_id = meta.get("request_id", "")

    if msg_type == "shutdown_request":
        # 回复 shutdown_response
        BUS.send(name, "lead", "Shutting down.",
                 "shutdown_response",
                 {"request_id": req_id, "approve": True})
        print(f"[Teammate {name}] Received shutdown request, responding and exiting")
        return True  # 停止循环

    if msg_type == "plan_approval_response":
        approve = meta.get("approve", False)
        status_text = "approved" if approve else "rejected"
        messages.append({
            "role": "user",
            "content": f"<plan_review status=\"{status_text}\">{msg['content']}</plan_review>",
        })
        print(f"[Teammate {name}] Plan {status_text} by lead")
        return False

    # 普通消息：注入到 messages
    messages.append({
        "role": "user",
        "content": f"<inbox>From {msg['from']}: {msg['content']}</inbox>",
    })
    return False


# ── s17: 队友任务工具 ──
def make_task_tools_for_teammate(name: str):
    """为队友创建任务管理工具函数。"""
    
    def teammate_list_tasks() -> str:
        """列出所有任务。"""
        from agent.tools.task_system import list_tasks
        return list_tasks()
    
    def teammate_claim_task(task_id: str) -> str:
        """认领任务（自动绑定 owner 为当前队友）。"""
        from agent.tools.task_system import claim_task
        return claim_task(task_id, owner=name)
    
    def teammate_complete_task(task_id: str) -> str:
        """完成任务。"""
        from agent.tools.task_system import complete_task
        return complete_task(task_id)
    
    return teammate_list_tasks, teammate_claim_task, teammate_complete_task


# ── s17: 身份重注入 ──
def ensure_identity_injected(messages: list, name: str, role: str) -> None:
    """
    如果 messages 被压缩（长度 <= 3），重新注入身份信息。
    防止 autoCompact 后队友丢失身份。
    """
    if len(messages) <= 3:
        messages.insert(0, {
            "role": "user",
            "content": f"<identity>You are '{name}', role: {role}. Continue your work.</identity>"
        })


# ── 队友线程（s17: 三阶段生命周期 WORK → IDLE → SHUTDOWN） ──
def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    """
    启动一个队友线程。s17 升级：
    - 新增 3 个任务工具: list_tasks, claim_task, complete_task
    - 三阶段生命周期: WORK → IDLE（idle_poll 轮询 60s） → SHUTDOWN
    - 队友自动认领任务看板上的未分配任务
    - 身份重注入：压缩后自动恢复身份
    """
    with teammate_lock:
        if name in active_teammates:
            return f"Teammate '{name}' already exists"
        active_teammates[name] = {
            "thread": None,
            "role": role,
            "status": "starting",
        }

    system = (
        f"You are '{name}', a {role}. Use tools to complete tasks. "
        "When you auto-claim a task from the board, work on it and use complete_task to mark it done. "
        "For complex tasks, use submit_plan to submit your plan for lead's review before executing. "
        "When done, send a summary to 'lead'."
    )

    def run():
        """队友线程的主逻辑。"""
        messages = [{"role": "user", "content": prompt}]

        # s17: 队友工具集 5 → 8（+ list_tasks, claim_task, complete_task）
        sub_tools = [
            {"type": "function", "function": {"name": "run_bash", "description": "Execute a shell command",
                "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
            {"type": "function", "function": {"name": "read_file", "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
            {"type": "function", "function": {"name": "write_file", "description": "Write content to a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
            {"type": "function", "function": {"name": "send_message", "description": "Send a message to another agent",
                "parameters": {"type": "object", "properties": {"to_agent": {"type": "string"}, "content": {"type": "string"}}, "required": ["to_agent", "content"]}}},
            {"type": "function", "function": {"name": "submit_plan", "description": "Submit a plan for lead's review before executing complex tasks",
                "parameters": {"type": "object", "properties": {"plan": {"type": "string", "description": "The plan to submit for review"}}, "required": ["plan"]}}},
            # s17: 新增任务工具
            {"type": "function", "function": {"name": "list_tasks", "description": "List all tasks on the board",
                "parameters": {"type": "object", "properties": {}}}},
            {"type": "function", "function": {"name": "claim_task", "description": "Claim a task from the board (auto-sets owner to you)",
                "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}}},
            {"type": "function", "function": {"name": "complete_task", "description": "Mark a task as completed",
                "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}}},
        ]

        # 工具函数映射（队友专属）
        teammate_send = make_send_message_for_teammate(name)
        teammate_submit_plan = make_submit_plan_for_teammate(name)
        teammate_list_tasks, teammate_claim_task, teammate_complete_task = make_task_tools_for_teammate(name)
        tool_funcs = {
            "run_bash": run_bash,
            "read_file": read_file,
            "write_file": write_file,
            "send_message": teammate_send,
            "submit_plan": teammate_submit_plan,
            "list_tasks": teammate_list_tasks,
            "claim_task": teammate_claim_task,
            "complete_task": teammate_complete_task,
        }

        # ── 外层循环: WORK → IDLE 交替，直到超时或关机 ──
        while True:
            summary = ""

            # ── WORK phase: 内层循环（最多 MAX_TEAMMATE_ROUNDS 轮 LLM 调用） ──
            with teammate_lock:
                active_teammates[name]["status"] = "running"

            for round_idx in range(MAX_TEAMMATE_ROUNDS):
                print(f"[Teammate {name}] WORK round {round_idx + 1}/{MAX_TEAMMATE_ROUNDS}")

                # s17: 身份重注入
                ensure_identity_injected(messages, name, role)

                # 检查收件箱 → dispatch
                inbox = BUS.read_inbox(name)
                should_stop = False
                for msg in inbox:
                    if handle_inbox_message(name, msg, messages):
                        should_stop = True
                        break
                if should_stop:
                    break

                # LLM 调用
                try:
                    response = LLM_CLIENT.chat.completions.create(
                        model=MODEL_ID,
                        messages=messages[-20:],
                        system=system,
                        tools=sub_tools,
                        max_tokens=8000,
                    )
                    message = response.choices[0].message
                except Exception as e:
                    print(f"[Teammate {name}] LLM error: {e}")
                    summary = f"Error: {e}"
                    break

                messages.append({"role": "assistant", "content": message.content or ""})

                # 没有工具调用 → WORK 阶段结束
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
                            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
                        except Exception as e:
                            messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Error: {e}"})
                    else:
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Unknown tool: {tool_name}"})

            if should_stop:
                # 收到 shutdown_request，直接退出
                break

            # ── SHUTDOWN 准备: 发 summary ──
            if not summary:
                summary = "Completed (no final message)"
            BUS.send(name, "lead", summary, "result")

            # ── IDLE phase: idle_poll 轮询 ──
            print(f"[Teammate {name}] Work phase done, entering IDLE...")
            with teammate_lock:
                active_teammates[name]["status"] = "idle"

            idle_result = idle_poll(name, messages, role)
            if idle_result == "shutdown":
                break
            if idle_result == "timeout":
                break
            # idle_result == "work" → 继续外层循环，回到 WORK

        # ── SHUTDOWN phase ──
        print(f"[Teammate {name}] Shutting down.")
        with teammate_lock:
            active_teammates[name]["status"] = "shutdown"

    # 启动线程
    thread = threading.Thread(target=run, daemon=True)
    with teammate_lock:
        active_teammates[name]["thread"] = thread
        active_teammates[name]["status"] = "running"
    thread.start()
    return f"Teammate '{name}' ({role}) started"


# ── Lead 的 inbox 注入（s16: 走 consume_lead_inbox） ──
def collect_teammate_messages() -> list[str]:
    """
    收集 Lead 收件箱中的队友消息，格式化为通知标签。
    走 consume_lead_inbox 统一路由协议消息。
    """
    messages = consume_lead_inbox()
    if not messages:
        return []

    notifications = []
    for msg in messages:
        msg_type = msg.get("type", "message")
        from_agent = msg.get("from", "unknown")
        content = msg.get("content", "")
        meta = msg.get("metadata", {})

        if msg_type == "result":
            notifications.append(
                f"<teammate_result>\n"
                f"  <from>{from_agent}</from>\n"
                f"  <summary>{content}</summary>\n"
                f"</teammate_result>"
            )
        elif msg_type == "plan_approval_request":
            req_id = meta.get("request_id", "")
            notifications.append(
                f"<plan_approval_request>\n"
                f"  <from>{from_agent}</from>\n"
                f"  <request_id>{req_id}</request_id>\n"
                f"  <plan>{content}</plan>\n"
                f"</plan_approval_request>"
            )
        elif msg_type == "shutdown_response":
            req_id = meta.get("request_id", "")
            approve = meta.get("approve", False)
            status = "approved" if approve else "rejected"
            notifications.append(
                f"<shutdown_response>\n"
                f"  <from>{from_agent}</from>\n"
                f"  <request_id>{req_id}</request_id>\n"
                f"  <status>{status}</status>\n"
                f"</shutdown_response>"
            )
        else:
            notifications.append(
                f"<teammate_message>\n"
                f"  <from>{from_agent}</from>\n"
                f"  <content>{content}</content>\n"
                f"</teammate_message>"
            )

    return notifications
