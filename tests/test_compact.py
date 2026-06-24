"""上下文压缩管线 — 能力边界测试。"""

import sys
import io
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.compact import (
    snip_compact, micro_compact, tool_result_budget,
    _estimate_tokens, apply_compression,
    MAX_MESSAGES, KEEP_RECENT_TOOL_RESULTS, MAX_TOOL_RESULT_BYTES,
    AUTOCOMPACT_TOKEN_THRESHOLD
)

print("=" * 60)
print("上下文压缩 — 能力边界测试")
print("=" * 60)

# === L1: snip_compact 测试 ===
print("\n--- L1: snip_compact ---")
print(f"配置: MAX_MESSAGES={MAX_MESSAGES}")

# 边界情况：恰好达到限制
msgs = [{"role": "user", "content": f"msg {i}"} for i in range(MAX_MESSAGES)]
result = snip_compact(msgs)
print(f"  边界值 ({MAX_MESSAGES} 条): {len(msgs)} -> {len(result)} (预期不变)")
assert len(result) == MAX_MESSAGES

# 边界情况：超过限制 1 条
msgs = [{"role": "user", "content": f"msg {i}"} for i in range(MAX_MESSAGES + 1)]
result = snip_compact(msgs)
print(f"  超限 ({MAX_MESSAGES+1} 条): {len(msgs)} -> {len(result)}")
assert len(result) == MAX_MESSAGES

# 大规模测试
msgs = [{"role": "user", "content": f"msg {i}"} for i in range(200)]
result = snip_compact(msgs)
print(f"  大规模 (200 条): -> {len(result)} (裁掉 {200 - len(result)})")
assert result[0]["content"] == "msg 0"
assert result[-1]["content"] == "msg 199"
print("  首尾保留: OK")

# 边界情况：空列表
msgs = []
result = snip_compact(msgs)
assert len(result) == 0
print("  空列表: OK")

# 边界情况：少于 KEEP_HEAD
msgs = [{"role": "user", "content": "只有一条"}]
result = snip_compact(msgs)
assert len(result) == 1
print("  单条消息: OK")

# === L2: micro_compact 测试 ===
print("\n--- L2: micro_compact ---")
print(f"配置: KEEP_RECENT_TOOL_RESULTS={KEEP_RECENT_TOOL_RESULTS}")

# 边界情况：恰好达到限制
msgs = [{"role": "tool", "tool_call_id": f"id{i}", "content": "x" * 200} for i in range(KEEP_RECENT_TOOL_RESULTS)]
result = micro_compact(msgs)
compacted = sum(1 for m in result if "compacted" in str(m.get("content", "")))
print(f"  边界值 ({KEEP_RECENT_TOOL_RESULTS} 条结果): {compacted} 条被压缩 (预期 0)")
assert compacted == 0

# 边界情况：超过限制 1 条
msgs = [{"role": "tool", "tool_call_id": f"id{i}", "content": "x" * 200} for i in range(KEEP_RECENT_TOOL_RESULTS + 1)]
result = micro_compact(msgs)
compacted = sum(1 for m in result if "compacted" in str(m.get("content", "")))
print(f"  超限 ({KEEP_RECENT_TOOL_RESULTS+1} 条结果): {compacted} 条被压缩 (预期 1)")
assert compacted == 1

# 短内容不应被压缩
msgs = [{"role": "tool", "tool_call_id": f"id{i}", "content": "短内容"} for i in range(10)]
result = micro_compact(msgs)
compacted = sum(1 for m in result if "compacted" in str(m.get("content", "")))
print(f"  短内容 (10 条结果, <120 字符): {compacted} 条被压缩 (预期 0)")
assert compacted == 0

# 最近的结果应该保留
msgs = [{"role": "tool", "tool_call_id": f"id{i}", "content": "x" * 200} for i in range(10)]
result = micro_compact(msgs)
for i in range(-KEEP_RECENT_TOOL_RESULTS, 0):
    assert len(result[i]["content"]) == 200, f"最近的结果 {i} 被压缩了!"
print(f"  最近 {KEEP_RECENT_TOOL_RESULTS} 条保留: OK")

# 混合消息：只影响 tool 角色
msgs = [
    {"role": "user", "content": "你好"},
    {"role": "tool", "tool_call_id": "t1", "content": "x" * 200},
    {"role": "assistant", "content": "思考中"},
    {"role": "tool", "tool_call_id": "t2", "content": "x" * 200},
    {"role": "tool", "tool_call_id": "t3", "content": "x" * 200},
    {"role": "tool", "tool_call_id": "t4", "content": "x" * 200},
]
result = micro_compact(msgs)
# user 和 assistant 不应被影响
assert result[0]["role"] == "user"
assert result[2]["role"] == "assistant"
# 只有 t1（最旧的工具结果）应该被压缩（保留最近 3 条: t2, t3, t4）
assert "compacted" in result[1]["content"]
print("  混合消息: 只有最旧的工具结果被压缩: OK")

# === L3: tool_result_budget 测试 ===
print("\n--- L3: tool_result_budget ---")
print(f"配置: MAX_TOOL_RESULT_BYTES={MAX_TOOL_RESULT_BYTES:,}")

# 低于预算
msgs = [{"role": "tool", "tool_call_id": "id1", "content": "x" * 1000}]
result = tool_result_budget(msgs)
assert "persisted-output" not in str(result[0]["content"])
print("  低于预算 (1KB): 不落盘, OK")

# 超过预算
big_content = "x" * 300_000  # 300KB
msgs = [{"role": "tool", "tool_call_id": "id1", "content": big_content}]
result = tool_result_budget(msgs)
has_persist = "persisted-output" in str(result[0]["content"])
print(f"  超过预算 (300KB): 落盘={has_persist}")
assert has_persist

# 验证文件已写入
import os
from pathlib import Path
persist_files = list(Path(".task_outputs/tool-results").glob("*.txt"))
print(f"  磁盘上的落盘文件: {len(persist_files)}")
assert len(persist_files) >= 1

# 验证预览保留
preview_len = len(result[0]["content"])
print(f"  预览长度: {preview_len:,} 字符 (原始: {len(big_content):,})")
assert preview_len < len(big_content)

# 多个工具结果，只落盘最大的
msgs = [
    {"role": "tool", "tool_call_id": "small", "content": "x" * 1000},
    {"role": "tool", "tool_call_id": "big", "content": "y" * 250_000},
]
result = tool_result_budget(msgs, max_bytes=200_000)
# 小的不应被影响
assert result[0]["content"] == "x" * 1000
# 大的应该被落盘
assert "persisted-output" in result[1]["content"]
print("  多个结果: 只落盘最大的: OK")

# === Token 估算测试 ===
print("\n--- Token 估算 ---")
msgs = [{"role": "user", "content": "hello world"}]
est = _estimate_tokens(msgs)
print(f'  "hello world" -> ~{est} tokens')

msgs = [{"role": "user", "content": "x" * 300_000}]
est = _estimate_tokens(msgs)
print(f"  300K 字符 -> ~{est:,} tokens (阈值: {AUTOCOMPACT_TOKEN_THRESHOLD:,})")

# === 完整管线测试 ===
print("\n--- 完整管线 ---")
msgs = [{"role": "system", "content": "你是一个助手。"}]
msgs.append({"role": "user", "content": "做很多工作"})
for i in range(30):
    msgs.append({"role": "assistant", "content": f"让我做第 {i} 步"})
    msgs.append({"role": "tool", "tool_call_id": f"tc{i}", "content": f"结果 {i} " + "x" * 500})
before_tokens = _estimate_tokens(msgs)
print(f"  管线前: {len(msgs)} 条消息, ~{before_tokens:,} tokens")

result = apply_compression(msgs)
after_tokens = _estimate_tokens(result)
print(f"  管线后:  {len(result)} 条消息, ~{after_tokens:,} tokens")
print(f"  减少: {before_tokens - after_tokens:,} tokens ({(1 - after_tokens/before_tokens)*100:.1f}%)")

# === 边界情况：空管线 ===
print("\n--- 边界情况 ---")
result = apply_compression([])
assert len(result) == 0
print("  空管线: OK")

result = apply_compression([{"role": "system", "content": "系统消息"}])
assert len(result) == 1
print("  单条系统消息: OK")

print("\n" + "=" * 60)
print("所有边界测试通过!")
print("=" * 60)
