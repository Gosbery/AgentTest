"""
Cron scheduler — run tasks on a schedule.

s14 新增：
  - CronJob dataclass: id, cron, prompt, recurring, durable
  - cron_matches: 五段式 cron 表达式匹配
  - cron_scheduler_loop: 独立 daemon 线程，每秒轮询
  - queue_processor_loop: Agent 空闲时自动交付定时任务
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
# CronJob Dataclass
# ============================================================================

@dataclass
class CronJob:
    """定时任务数据结构。"""
    id: str
    cron: str          # "0 9 * * *" 五段式 cron 表达式
    prompt: str        # 触发时注入给 Agent 的消息
    recurring: bool    # True=周期性，False=一次性
    durable: bool      # True=写磁盘，跨会话保留


# ============================================================================
# State
# ============================================================================

_job_counter = 0
scheduled_jobs: dict[str, CronJob] = {}   # job_id → CronJob
_last_fired: dict[str, str] = {}          # job_id → "YYYY-MM-DD HH:MM"
cron_queue: list[CronJob] = []            # 调度线程写入，agent_loop 消费
cron_lock = threading.Lock()
agent_lock = threading.Lock()             # 判断 Agent 是否空闲


# ============================================================================
# Storage helpers (durable)
# ============================================================================

def _durable_path() -> Path:
    return WORKDIR / ".scheduled_tasks.json"


def save_durable_jobs() -> None:
    """Save durable jobs to disk."""
    jobs = [asdict(job) for job in scheduled_jobs.values() if job.durable]
    _durable_path().write_text(
        json.dumps({"tasks": jobs}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_durable_jobs() -> int:
    """Load durable jobs from disk. Returns count loaded."""
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
                print(f"[cron] skipping invalid job {job.id}: {err}")
                continue
            scheduled_jobs[job.id] = job
            count += 1
        except Exception as e:
            print(f"[cron] skipping bad job: {e}")
    return count


# ============================================================================
# Cron expression matching
# ============================================================================

def _cron_field_matches(field: str, value: int) -> bool:
    """Match a single cron field against a value.

    Supports: *, */N, N, N-M, N,M,...
    """
    if field == "*":
        return True

    # Comma-separated list
    for part in field.split(","):
        part = part.strip()

        # Step: */N or N-M/S
        if "/" in part:
            base, step_str = part.split("/", 1)
            step = int(step_str)
            if base == "*":
                return value % step == 0
            if "-" in base:
                lo, hi = base.split("-", 1)
                return int(lo) <= value <= int(hi) and (value - int(lo)) % step == 0
            return value == int(base)

        # Range: N-M
        if "-" in part:
            lo, hi = part.split("-", 1)
            return int(lo) <= value <= int(hi)

        # Exact: N
        if part.isdigit():
            return value == int(part)

    return False


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a cron expression matches the given datetime."""
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False

    minute, hour, dom, month, dow = fields
    # Python Monday=0 → cron Sunday=0
    dow_val = (dt.weekday() + 1) % 7

    m = _cron_field_matches(minute, dt.minute)
    h = _cron_field_matches(hour, dt.hour)
    dom_ok = _cron_field_matches(dom, dt.day)
    month_ok = _cron_field_matches(month, dt.month)
    dow_ok = _cron_field_matches(dow, dow_val)

    if not (m and h and month_ok):
        return False

    # DOM and DOW: both constrained → either matching is enough (OR)
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
    """Validate a cron expression. Returns error string or None."""
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return f"Expected 5 fields, got {len(fields)}"

    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["minute", "hour", "day-of-month", "month", "day-of-week"]

    for field, (lo, hi), name in zip(fields, ranges, names):
        for part in field.split(","):
            part = part.strip()
            if "/" in part:
                base, step_str = part.split("/", 1)
                if not step_str.isdigit() or int(step_str) == 0:
                    return f"Invalid step in {name}: {part}"
                if base != "*" and not base.isdigit() and "-" not in base:
                    return f"Invalid base in {name}: {part}"
            elif part == "*":
                continue
            elif "-" in part:
                lo_s, hi_s = part.split("-", 1)
                if not (lo_s.isdigit() and hi_s.isdigit()):
                    return f"Invalid range in {name}: {part}"
            elif not part.isdigit():
                return f"Invalid value in {name}: {part}"

    return None


# ============================================================================
# Job management
# ============================================================================

def _generate_job_id() -> str:
    ts = int(time.time())
    rand_hex = format(random.randint(0, 0xFFFF), "04x")
    return f"cron_{ts}_{rand_hex}"


def schedule_job(cron: str, prompt: str,
                 recurring: bool = True,
                 durable: bool = True) -> str:
    """Register a new cron job. Returns success/error message."""
    err = validate_cron(cron)
    if err:
        return f"Invalid cron expression: {err}"

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

    kind = "recurring" if recurring else "one-shot"
    storage = "durable" if durable else "session-only"
    return f"Scheduled {kind} job {job_id}: \"{cron}\" [{storage}]"


def cancel_job(job_id: str) -> str:
    """Cancel a cron job."""
    with cron_lock:
        job = scheduled_jobs.pop(job_id, None)
        if job and job.durable:
            save_durable_jobs()

    if job:
        return f"Cancelled job {job_id}"
    return f"Job {job_id} not found"


def list_jobs() -> str:
    """List all scheduled cron jobs."""
    with cron_lock:
        jobs = list(scheduled_jobs.values())

    if not jobs:
        return "No scheduled cron jobs."

    lines = ["\n## Scheduled Jobs"]
    for job in jobs:
        kind = "recurring" if job.recurring else "one-shot"
        storage = "durable" if job.durable else "session"
        lines.append(f"  {job.id}: \"{job.cron}\" → {job.prompt[:40]} [{kind}, {storage}]")
    return "\n".join(lines)


# ============================================================================
# Queue helpers
# ============================================================================

def has_cron_queue() -> bool:
    """Check if there are pending cron tasks."""
    with cron_lock:
        return len(cron_queue) > 0


def consume_cron_queue() -> list[CronJob]:
    """Drain the cron queue, returning all pending jobs."""
    with cron_lock:
        jobs = list(cron_queue)
        cron_queue.clear()
    return jobs


# ============================================================================
# Scheduler thread (producer)
# ============================================================================

def cron_scheduler_loop() -> None:
    """
    Daemon thread: polls every 1 second, fires matching jobs into cron_queue.
    """
    while True:
        time.sleep(1)
        now = datetime.now()
        minute_marker = now.strftime("%Y-%m-%d %H:%M")

        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now):
                        if _last_fired.get(job.id) != minute_marker:
                            cron_queue.append(job)
                            _last_fired[job.id] = minute_marker
                            print(f"[cron] fired {job.id}: {job.prompt[:40]}")

                        if not job.recurring:
                            scheduled_jobs.pop(job.id, None)
                            if job.durable:
                                save_durable_jobs()
                except Exception as e:
                    print(f"[cron error] {job.id}: {e}")


# ============================================================================
# Queue processor thread (delivery)
# ============================================================================

def queue_processor_loop() -> None:
    """
    Daemon thread: when cron_queue has tasks and agent is idle,
    acquire agent_lock and deliver.
    """
    while True:
        time.sleep(0.2)
        if not has_cron_queue():
            continue
        if not agent_lock.acquire(blocking=False):
            continue
        try:
            if has_cron_queue():
                print("[queue processor] Agent idle, delivering cron tasks")
                # The agent_loop will call consume_cron_queue()
                # We just signal by keeping the lock held
                # and letting the main loop pick it up
        finally:
            agent_lock.release()


# ============================================================================
# Startup
# ============================================================================

def start_cron_scheduler() -> None:
    """Load durable jobs and start scheduler + queue processor threads."""
    count = load_durable_jobs()
    if count:
        print(f"[cron] Loaded {count} durable job(s)")

    scheduler_thread = threading.Thread(target=cron_scheduler_loop, daemon=True)
    scheduler_thread.start()

    processor_thread = threading.Thread(target=queue_processor_loop, daemon=True)
    processor_thread.start()

    print("[cron] Scheduler started")
