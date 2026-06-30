"""
定时调度器 — 按时间表自动触发任务。

s14 新增：
  - CronJob 数据类：id, cron, prompt, recurring, durable
  - cron_matches：五段式 cron 表达式匹配
  - cron_scheduler_loop：独立 daemon 线程，每秒轮询
  - queue_processor_loop：Agent 空闲时自动交付定时任务
  - durable 持久化到 .scheduled_tasks.json
"""

import json
import time
import threading
import random
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from agent.config import WORKDIR


# ============================================================================
# CronJob 数据类
# ============================================================================

@dataclass
class CronJob:
    """定时任务数据结构。"""
    id: str
    cron: str          # 五段式 cron 表达式，如 "0 9 * * *"
    prompt: str        # 触发时注入给 Agent 的消息
    recurring: bool    # True=周期性，False=一次性
    durable: bool      # True=写磁盘，跨会话保留


# ============================================================================
# 全局状态
# ============================================================================

_job_counter = 0
scheduled_jobs: dict[str, CronJob] = {}   # 任务 ID → CronJob
_last_fired: dict[str, str] = {}          # 任务 ID → "YYYY-MM-DD HH:MM"（上次触发时间）
cron_queue: list[CronJob] = []            # 调度线程写入，agent_loop 消费
cron_lock = threading.Lock()              # 保护 scheduled_jobs 和 cron_queue 的线程锁
agent_lock = threading.Lock()             # 判断 Agent 是否空闲


# ============================================================================
# 持久化存储
# ============================================================================

def _durable_path() -> Path:
    """
    获取持久化文件路径。

    返回:
        .scheduled_tasks.json 的完整路径
    """
    return WORKDIR / ".scheduled_tasks.json"


def save_durable_jobs() -> None:
    """
    将 durable 任务保存到磁盘。

    仅保存 durable=True 的任务，序列化为 JSON 写入 .scheduled_tasks.json。
    """
    jobs = [asdict(job) for job in scheduled_jobs.values() if job.durable]
    _durable_path().write_text(
        json.dumps({"tasks": jobs}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_durable_jobs() -> int:
    """
    从磁盘加载 durable 任务。

    加载时会校验 cron 表达式，非法任务会被跳过并打印警告。

    返回:
        成功加载的任务数量
    """
    path = _durable_path()
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for item in data.get("tasks", []):
        try:
            job = CronJob(**item)
            err = validate_cron(job.cron)
            if err:
                print(f"[cron] 跳过非法任务 {job.id}: {err}")
                continue
            scheduled_jobs[job.id] = job
            count += 1
        except Exception as e:
            print(f"[cron] 跳过损坏的任务: {e}")
    return count


# ============================================================================
# Cron 表达式匹配
# ============================================================================

def _cron_field_matches(field: str, value: int) -> bool:
    """
    匹配单个 cron 字段与给定值。

    参数:
        field: cron 字段字符串，支持 *, */N, N, N-M, N,M,...
        value: 当前时间对应的数值

    返回:
        是否匹配
    """
    if field == "*":
        return True

    # 逗号分隔列表
    for part in field.split(","):
        part = part.strip()

        # 步进: */N 或 N-M/S
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                return value % step == 0
            if "-" in base:
                lo, hi = base.split("-", 1)
                return int(lo) <= value <= int(hi) and (value - int(lo)) % step == 0
            return value == int(base)

        # 范围: N-M
        if "-" in part:
            lo, hi = part.split("-", 1)
            return int(lo) <= value <= int(hi)

        # 精确值: N
        if part.isdigit():
            return value == int(part)

    return False


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """
    判断 cron 表达式是否匹配给定时间。

    参数:
        cron_expr: 五段式 cron 表达式（分钟 小时 日 月 星期）
        dt: 要匹配的 datetime 对象

    返回:
        是否匹配

    说明:
        日（DOM）和星期（DOW）同时被约束时，任一匹配即可（OR 语义）。
        这是 Unix cron 的标准行为。
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False

    minute, hour, dom, month, dow = fields
    # Python weekday: Monday=0 → cron: Sunday=0
    dow_val = (dt.weekday() + 1) % 7

    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)

    if not (m and h and month_ok):
        return False

    # 日和星期：两者都有约束时任一匹配即可（OR）
    dom_unconstrained = dom == "*"
    dow_unconstrained = dow == "*"
    if dom_unconstrained and dow_unconstrained:
        return True
    if dom_unconstrained:
        return dow_ok
    if dow_unconstrained:
        return dom_ok
    return dom_ok or dow_ok


def validate_cron(cron_expr: str) -> str | None:
    """
    校验 cron 表达式是否合法。

    参数:
        cron_expr: 五段式 cron 表达式

    返回:
        错误描述字符串，合法时返回 None
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return f"期望 5 个字段，实际 {len(fields)} 个"

    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["分钟", "小时", "日", "月", "星期"]

    for field, (lo, hi), name in zip(fields, ranges, names):
        for part in field.split(","):
            part = part.strip()
            if "/" in part:
                base, step_str = part.split("/", 1)
                if not step_str.isdigit() or int(step_str) == 0:
                    return f"{name} 步进无效: {part}"
                if base != "*" and not base.isdigit() and "-" not in base:
                    return f"{name} 基数无效: {part}"
            elif part == "*":
                continue
            elif "-" in part:
                lo_s, hi_s = part.split("-", 1)
                if not (lo_s.isdigit() and hi_s.isdigit()):
                    return f"{name} 范围无效: {part}"
            elif not part.isdigit():
                return f"{name} 值无效: {part}"

    return None


# ============================================================================
# 任务管理
# ============================================================================

def _generate_job_id() -> str:
    """
    生成任务 ID。

    格式: cron_{时间戳}_{4位随机hex}
    """
    ts = int(time.time())
    rand_hex = format(random.randint(0, 0xFFFF), "04x")
    return f"cron_{ts}_{rand_hex}"


def schedule_job(cron: str, prompt: str,
                 recurring: bool = True,
                 durable: bool = True) -> str:
    """
    注册新的定时任务。

    参数:
        cron: 五段式 cron 表达式（分钟 小时 日 月 星期）
        prompt: 触发时注入给 Agent 的消息
        recurring: True=周期性任务，False=一次性任务（默认 True）
        durable: True=持久化到磁盘，False=仅当前会话（默认 True）

    返回:
        成功或错误的结果消息
    """
    err = validate_cron(cron)
    if err:
        return f"cron 表达式无效: {err}"

    global _job_counter
    with cron_lock:
        _job_counter += 1
        job_id = _generate_job_id()
        job = CronJob(
            id=job_id,
            cron=cron,
            prompt=prompt,
            recurring=recurring,
            durable=durable,
        )
        scheduled_jobs[job_id] = job

    if durable:
        save_durable_jobs()

    kind = "周期性" if recurring else "一次性"
    storage = "持久化" if durable else "仅会话"
    return f"已调度{kind}任务 {job_id}: \"{cron}\" [{storage}]"


def cancel_job(job_id: str) -> str:
    """
    取消定时任务。

    参数:
        job_id: 要取消的任务 ID

    返回:
        取消结果消息
    """
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
        if job and job.durable:
            save_durable_jobs()

    if job:
        return f"已取消任务 {job_id}"
    return f"任务 {job_id} 不存在"


def list_jobs() -> str:
    """
    列出所有已调度的定时任务。

    返回:
        任务列表摘要文本
    """
    with cron_lock:
        jobs = list(scheduled_jobs.values())

    if not jobs:
        return "没有已调度的定时任务。"

    lines = ["\n## 已调度任务"]
    for job in jobs:
        kind = "周期性" if job.recurring else "一次性"
        storage = "持久化" if job.durable else "仅会话"
        lines.append(f"  {job.id}: \"{job.cron}\" → {job.prompt[:40]} [{kind}, {storage}]")
    return "\n".join(lines)


# ============================================================================
# 队列操作
# ============================================================================

def has_cron_queue() -> bool:
    """
    检查是否有待处理的定时任务。

    返回:
        队列是否非空
    """
    with cron_lock:
        return len(cron_queue) > 0


def consume_cron_queue() -> list[CronJob]:
    """
    消费队列中所有待处理的定时任务。

    返回:
        所有待处理的 CronJob 列表，队列随后被清空
    """
    with cron_lock:
        jobs = list(cron_queue)
        cron_queue.clear()
    return jobs


# ============================================================================
# 调度线程（生产者）
# ============================================================================

def cron_scheduler_loop() -> None:
    """
    调度线程主循环。

    作为 daemon 线程运行，每秒轮询一次，检查是否有任务到期。
    到期的任务被放入 cron_queue，由 agent_loop 消费。
    一次性任务触发后自动从 scheduled_jobs 中移除。
    单个任务的异常不会影响其他任务。
    """
    while True:
        time.sleep(1)
        now = datetime.now()
        minute_marker = now.strftime("%Y-%m-%d %H:%M")

        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now):
                        # 同一分钟内不重复触发
                        if _last_fired.get(job.id) != minute_marker:
                            cron_queue.append(job)
                            _last_fired[job.id] = minute_marker
                            print(f"[cron] 触发 {job.id}: {job.prompt[:40]}")

                        # 一次性任务触发后移除
                        if not job.recurring:
                            scheduled_jobs.pop(job.id, None)
                            if job.durable:
                                save_durable_jobs()
                except Exception as e:
                    print(f"[cron 错误] {job.id}: {e}")


# ============================================================================
# 队列处理线程（交付者）
# ============================================================================

def queue_processor_loop() -> None:
    """
    队列处理线程主循环。

    作为 daemon 线程运行，每 0.2 秒检查一次。
    当 cron_queue 非空且 Agent 空闲时，通知 agent_loop 交付定时任务。
    通过 agent_lock 判断 Agent 是否空闲，避免在执行中途打断。
    """
    while True:
        time.sleep(0.2)
        if not has_cron_queue():
            continue
        if not agent_lock.acquire(blocking=False):
            continue  # Agent 在忙，等下一轮
        try:
            if has_cron_queue():
                print("[队列处理器] Agent 空闲，交付定时任务")
                # agent_loop 会调用 consume_cron_queue() 消费任务
        finally:
            agent_lock.release()


# ============================================================================
# 启动入口
# ============================================================================

def start_cron_scheduler() -> None:
    """
    启动定时调度器。

    加载磁盘上的 durable 任务，然后启动两个 daemon 线程：
      1. 调度线程：每秒轮询，到期任务写入 cron_queue
      2. 队列处理线程：Agent 空闲时交付队列中的任务
    """
    count = load_durable_jobs()
    if count:
        print(f"[cron] 已加载 {count} 个持久化任务")

    scheduler_thread = threading.Thread(target=cron_scheduler_loop, daemon=True)
    scheduler_thread.start()

    processor_thread = threading.Thread(target=queue_processor_loop, daemon=True)
    processor_thread.start()

    print("[cron] 调度器已启动")
