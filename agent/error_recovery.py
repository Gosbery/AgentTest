"""
错误恢复模块 — 三种恢复路径 + 指数退避。

s11 新增：
  - 路径 1: max_tokens -> 升级 8K->64K，然后续写提示（最多 3 次）
  - 路径 2: prompt_too_long -> reactive compact -> 重试（1 次）
  - 路径 3: 429/529 -> 指数退避 + 抖动（最多 10 次），连续 529 切换备用模型
  - with_retry 包装器处理瞬态错误
  - RecoveryState 跟踪升级/压缩/529/模型状态
"""

import random
import time
from typing import Callable, Any

from agent.config import (
    DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS,
    MAX_RECOVERY_RETRIES,
    MAX_RETRIES,
    BASE_DELAY_MS,
    MAX_CONSECUTIVE_529,
    FALLBACK_MODEL,
    CONTINUATION_PROMPT,
)


class RecoveryState:
    """跟踪跨循环的恢复尝试。"""

    def __init__(self):
        self.has_escalated = False  # 是否已升级 max_tokens
        self.recovery_count = 0  # 续写尝试次数
        self.consecutive_529 = 0  # 连续 529 错误计数
        self.has_attempted_reactive_compact = False  # 是否已尝试应急压缩
        self.current_model = None  # 当前使用的模型（None 表示使用默认）


def retry_delay(attempt: int, retry_after: int = None) -> float:
    """
    指数退避 + 抖动。Retry-After 优先。

    Args:
        attempt: 当前尝试次数（从 0 开始）
        retry_after: 服务器返回的 Retry-After 值（秒）

    Returns:
        等待的秒数
    """
    if retry_after:
        return retry_after
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    jitter = random.uniform(0, base * 0.25)
    return base + jitter


def is_rate_limit_error(e: Exception) -> bool:
    """检查是否是 429 限流错误。"""
    error_str = str(e).lower()
    return "ratelimit" in error_str or "429" in error_str or "rate limit" in error_str


def is_overloaded_error(e: Exception) -> bool:
    """检查是否是 529 过载错误。"""
    error_str = str(e).lower()
    return "overloaded" in error_str or "529" in error_str


def is_prompt_too_long_error(e: Exception) -> bool:
    """检查是否是上下文过长错误。"""
    error_str = str(e).lower()
    return (
        "prompt_too_long" in error_str
        or "prompt" in error_str and "long" in error_str
        or "context_length" in error_str
        or "maximum context" in error_str
        or "max_context_window" in error_str
    )


def with_retry(fn: Callable, state: RecoveryState) -> Any:
    """
    瞬态错误（429/529）的指数退避包装器。

    非瞬态错误会重新抛出给外层处理。

    Args:
        fn: 要执行的函数
        state: 恢复状态

    Returns:
        函数执行结果

    Raises:
        RuntimeError: 超过最大重试次数
        Exception: 非瞬态错误
    """
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0  # 成功则重置 529 计数
            return result
        except Exception as e:
            # 429 限流 -> 指数退避
            if is_rate_limit_error(e):
                delay = retry_delay(attempt)
                print(f"  \033[33m[429 rate limit] retry {attempt+1}/{MAX_RETRIES}, "
                      f"wait {delay:.1f}s\033[0m")
                time.sleep(delay)
                continue

            # 529 过载 -> 指数退避 + 可能切换模型
            if is_overloaded_error(e):
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529:
                    if FALLBACK_MODEL:
                        state.current_model = FALLBACK_MODEL
                        state.consecutive_529 = 0
                        print(f"  \033[31m[529 x{MAX_CONSECUTIVE_529}] "
                              f"switching to {FALLBACK_MODEL}\033[0m")
                    else:
                        state.consecutive_529 = 0
                        print(f"  \033[31m[529 x{MAX_CONSECUTIVE_529}] "
                              f"no FALLBACK_MODEL_ID configured, continuing retry\033[0m")
                delay = retry_delay(attempt)
                print(f"  \033[33m[529 overloaded] retry {attempt+1}/{MAX_RETRIES}, "
                      f"wait {delay:.1f}s\033[0m")
                time.sleep(delay)
                continue

            # 非瞬态错误 -> 重新抛出给外层处理
            raise

    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")


def reactive_compact(messages: list) -> list:
    """
    应急压缩 — 教学版保留最后 N 条消息。

    真实实现会调用 LLM 生成压缩摘要，然后重试。
    教学版简化为只保留尾部消息，因为 s08/s09 已经覆盖了基于 LLM 的压缩。

    Args:
        messages: 对话消息列表

    Returns:
        压缩后的消息列表
    """
    print("  \033[31m[reactive compact] trimming to last 5 messages\033[0m")
    tail = messages[-5:]
    return [{
        "role": "user",
        "content": "[Reactive compact] Earlier conversation trimmed. "
                   "Continue from where you left off."
    }, *tail]
