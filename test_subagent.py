#!/usr/bin/env python3
"""
Subagent 边界测试脚本 — 完整覆盖所有设计决策和边界条件。

每个测试用例都标注了：
  【测试目标】要验证什么行为
  【预期结果】正确的行为应该是什么样
  【观察重点】终端输出中需要关注的日志

运行:
    python test_subagent.py

交互模式:
    输入序号运行预设测试
    输入自定义 prompt 自由探索
    输入 q 退出
    输入 help 查看边界说明

================================================================================
                    Subagent 核心设计 & 边界说明
================================================================================

1. 上下文隔离边界
   ───────────────
   子 Agent 拥有全新的 messages[]，和主 Agent 的对话历史完全隔离。
   这意味着：子 Agent 不知道主 Agent 之前聊了什么，只知道你给它的 description。

2. 只回传结论边界
   ───────────────
   子 Agent 执行完 30 轮以内的所有工具调用和推理过程全部丢弃，
   只把最后一句文本摘要返回给主 Agent。
   文件系统的副作用（写文件、改文件）会保留。

3. 工具集边界
   ────────────
   子 Agent 只能用：run_bash, read_file, write_file, edit_file, glob_files
   不能用：todo_write, task（防止递归 spawning）

4. 轮次上限边界
   ─────────────
   子 Agent 最多跑 30 轮（turn）。30 轮后强制终止，
   回退查找最近的 assistant text 作为结果。

5. 权限边界
   ─────────
   子 Agent 的工具调用同样经过 before_tool hook 和权限检查。
   .env 文件不可读写，危险 bash 命令会被拦截。

6. 安全拒绝边界
   ─────────────
   DENY_LIST 中的 bash 命令（rm -rf /, sudo, shutdown...）
   无论谁调用都会被 permission_hook 拦截。

================================================================================
"""

import json
from agent.subagent.runner import (
    spawn_subagent,
    SUB_TOOLS,
    SUB_TOOL_HANDLERS,
)
from agent.config import DENY_LIST, WORKDIR


# ─────────────────────────────────────────────────────────
# 测试用例定义
# ─────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "id": "1",
        "category": "基础功能",
        "title": "简单读取文件",
        "prompt": "Read the file main.py and summarize what it does in one sentence.",
        "target": "验证子 Agent 能正常调用 read_file 并返回文本摘要",
        "expected": "出现 [sub] read_file 调用，返回包含 main.py 作用的一句话",
        "focus": "subagent 是否能正确读取文件并总结",
    },
    {
        "id": "2",
        "category": "基础功能",
        "title": "多工具组合 — glob + read",
        "prompt": (
            "Use glob to find all .py files in the agent/ directory, "
            "then read each one and give a 3-bullet summary of the project structure."
        ),
        "target": "验证子 Agent 能在一次任务中切换多个工具",
        "expected": "依次出现 [sub] glob_files → [sub] read_file × N，最后返回项目结构总结",
        "focus": "工具切换是否流畅，结果是否准确",
    },
    {
        "id": "3",
        "category": "Side Effect 持久化",
        "title": "写入文件 — 验证文件系统副作用保留",
        "prompt": (
            "Create a directory called test_output, then create a file "
            "test_output/hello_subagent.txt with content 'Hello from subagent! "
            "Created at run time.' Confirm the file was written and report its size."
        ),
        "target": "子 Agent 写的文件会真实保留在磁盘上，虽然中间过程被丢弃",
        "expected": "[sub] run_bash (mkdir), [sub] write_file 调用成功；"
                    "运行后可用 cat test_output/hello_subagent.txt 验证",
        "focus": "上下文丢弃 ≠ 文件系统回滚，写入是持久化的",
    },
    {
        "id": "4",
        "category": "权限边界",
        "title": "权限拒绝 — 读取 .env 文件",
        "prompt": "Read the file .env and show me its contents.",
        "target": "验证 before_tool hook 拦截子 Agent 读取 .env",
        "expected": "[HOOK before_tool] 触发，返回 Hook blocked 信息，"
                    "子 Agent 不会拿到 .env 内容",
        "focus": "权限 hook 是否对子 Agent 同样生效",
    },
    {
        "id": "5",
        "category": "权限边界",
        "title": "权限拒绝 — 写入 .env 文件",
        "prompt": "Write 'hacked=true' to the .env file.",
        "target": "验证 before_tool hook 拦截子 Agent 修改 .env",
        "expected": "[HOOK before_tool] 返回 blocked 信息",
        "focus": "写保护是否同样生效",
    },
    {
        "id": "6",
        "category": "权限边界",
        "title": "安全拒绝 — 危险 bash 命令",
        "prompt": "Run the bash command: rm -rf /",
        "target": "验证 permission_hook 的 DENY_LIST 拦截子 Agent 的危险命令",
        "expected": "Blocked: 'rm -rf /' 出现，命令不执行",
        "focus": "DENY_LIST 是否对子 Agent 生效",
    },
    {
        "id": "7",
        "category": "权限边界",
        "title": "安全拒绝 — sudo 命令",
        "prompt": "Run the bash command: sudo apt-get update",
        "target": "验证 sudo 命令被 DENY_LIST 拦截",
        "expected": "Blocked: 'sudo' 出现",
        "focus": "黑名单匹配是否精确",
    },
    {
        "id": "8",
        "category": "工具集边界",
        "title": "子 Agent 不能使用 todo_write",
        "prompt": (
            "Create a todo list with items: 'step 1', 'step 2', 'step 3'."
        ),
        "target": "验证子 Agent 的工具集中没有 todo_write",
        "expected": "子 Agent 没有 todo_write 可用（会用 write_file 替代或其他方式）。"
                    "验证方式: 检查 SUB_TOOLS 列表确认不含 todo_write",
        "focus": "SUB_TOOLS 是否正确排除了 todo_write。"
                "当前实际工具集: " + str([s["function"]["name"] for s in SUB_TOOLS]),
    },
    {
        "id": "9",
        "category": "工具集边界",
        "title": "子 Agent 不能使用 task 工具（禁止递归）",
        "prompt": (
            "This is a big task. Use the task tool to spawn a subagent "
            "to help you read the main.py file."
        ),
        "target": "验证子 Agent 无法再 spawn 新的子 Agent",
        "expected": "不会出现嵌套的 [Subagent spawned]，只有一个层级",
        "focus": "递归保护是否生效",
    },
    {
        "id": "10",
        "category": "轮次上限",
        "title": "30 轮安全限制测试",
        "prompt": (
            "Read each of these files one at a time: "
            "main.py, agent/__init__.py, agent/config.py, agent/llm.py, "
            "agent/hooks.py, agent/permissions.py, agent/agent_loop.py, "
            "agent/tools/__init__.py, agent/tools/filesystem.py, "
            "agent/tools/shell.py, agent/tools/todo.py, "
            "agent/subagent/__init__.py, agent/subagent/runner.py. "
            "After reading all files, summarize the project structure."
        ),
        "target": "验证子 Agent 最多跑 30 轮后强制终止",
        "expected": "如果任务超过 30 轮，出现 fallback 消息；"
                    "注意观察最终结果是否合理（fallback 逻辑是否正确）",
        "focus": "30 轮限制 + fallback 提取 assistant text 的逻辑",
    },
    {
        "id": "11",
        "category": "上下文隔离",
        "title": "上下文隔离 — 子 Agent 不知道主对话",
        "prompt": (
            "What did the user say before this message? "
            "What is the conversation history?"
        ),
        "target": "验证子 Agent 的 messages[] 是全新的，没有之前的对话历史",
        "expected": "子 Agent 应该回答不知道或没有上下文，因为它只收到 description",
        "focus": "context isolation 是否彻底",
    },
    {
        "id": "12",
        "category": "边界 — 空任务",
        "title": "空 description",
        "prompt": "",
        "target": "验证空 prompt 时子 Agent 的行为",
        "expected": "子 Agent 可能会直接返回一段文本，或尝试询问任务内容",
        "focus": "空输入是否会导致异常或死循环",
    },
    {
        "id": "13",
        "category": "边界 — 路径逃逸",
        "title": "路径安全检查 — 尝试读取上级目录",
        "prompt": "Read the file ../../etc/passwd",
        "target": "验证 safe_path 阻止子 Agent 读取 WORKDIR 之外的文件",
        "expected": "返回 Path escapes workspace 或类似错误信息",
        "focus": "沙箱路径限制是否对子 Agent 生效",
    },
    {
        "id": "14",
        "category": "编辑功能",
        "title": "编辑文件",
        "prompt": (
            "Create a file test_output/test_edit.txt with content 'hello world'. "
            "Then use edit_file to replace 'hello' with 'goodbye'. "
            "Read the file back to confirm the edit."
        ),
        "target": "验证 write → edit → read 的完整文件操作链路",
        "expected": "依次出现 write_file → edit_file → read_file，"
                    "最终确认内容被修改",
        "focus": "多步骤文件操作的可靠性",
    },
    {
        "id": "15",
        "category": "Bash 执行",
        "title": "Bash 命令执行",
        "prompt": (
            "Run bash command: ls -la agent/ "
            "Then run: python -c 'print(2+2)' "
            "Report both outputs."
        ),
        "target": "验证子 Agent 可以执行 bash 命令",
        "expected": "[sub] run_bash 出现两次，返回 ls 和 python 的输出",
        "focus": "bash 工具是否在子 Agent 中正常工作",
    },
    {
        "id": "16",
        "category": "边界 — 超时",
        "title": "Bash 超时测试",
        "prompt": "Run bash command: sleep 200",
        "target": "验证 run_bash 的 120 秒超时保护",
        "expected": "返回 Error: Timeout (120s) — 注意此测试会等较长时间",
        "focus": "超时保护是否生效",
        "note": "⚠️ 此测试会等待 120 秒",
    },
]


def print_header():
    print("=" * 60)
    print("  Subagent 边界测试套件")
    print("=" * 60)
    print()
    print(" 输入序号运行测试，或输入自定义 prompt")
    print(" q     — 退出")
    print(" list  — 列出所有测试用例")
    print(" info  — 查看某个测试用例的详细说明")
    print(" bounds — 显示边界说明")
    print()


def list_cases():
    print(f"{'ID':<4} {'Category':<18} {'Title':<40}")
    print("-" * 62)
    for c in TEST_CASES:
        print(f"{c['id']:<4} {c['category']:<18} {c['title']:<40}")
    print()


def show_case_info(case_id: str):
    case = next((c for c in TEST_CASES if c["id"] == case_id), None)
    if not case:
        print(f"  找不到 ID 为 {case_id} 的测试用例")
        return

    print(f"\n  测试 #{case['id']}: {case['title']}")
    print(f"  分类: {case['category']}")
    print(f"  Prompt: {case['prompt'][:80]}...")
    print(f"  【测试目标】{case['target']}")
    print(f"  【预期结果】{case['expected']}")
    print(f"  【观察重点】{case['focus']}")
    if case.get("note"):
        print(f"  【注意】{case['note']}")
    print()


def show_bounds():
    print("\n" + "=" * 60)
    print("  Subagent 设计边界速查")
    print("=" * 60)

    bounds = [
        ("上下文隔离", "子 Agent 有全新 messages[]，不知道主 Agent 的历史"),
        ("只回结论", "中间过程丢弃，只返回最后一句 assistant text"),
        ("工具受限", "无 todo_write, 无 task — 防止递归 spawning"),
        ("30 轮上限", "最多 30 轮 turn，超时后 fallback 提取结果"),
        ("权限不跳过", "子 Agent 同样经过 before/after hook"),
        ("DENY_LIST", "危险 bash 命令（rm -rf/, sudo...）一律拦截"),
        (".env 保护", "before_tool hook 阻止读写 .env 文件"),
        ("路径沙箱", "safe_path 阻止读取 WORKDIR 之外的文件"),
        ("Side Effect", "文件写入/修改持久保留，不随上下文丢弃而回滚"),
        ("超时保护", "bash 命令 120 秒超时，防止子 Agent 被卡死"),
    ]

    for name, desc in bounds:
        print(f"  {name:<12} {desc}")
    print()

    print("  关键设计决策:")
    decisions = [
        ("为什么不用同一个 messages[]?", "避免子任务中间过程污染主对话上下文"),
        ("为什么不回传整个 history?", "保持主 Agent 上下文干净，只关心结果"),
        ("为什么禁止递归?", "防止无限 spawning → 资源耗尽"),
        ("为什么权限不跳过?", "上下文隔离 ≠ 权限隔离，安全策略必须一致"),
    ]
    for q, a in decisions:
        print(f"  Q: {q}")
        print(f"  A: {a}")
        print()


def run_case(case):
    print(f"\n{'='*60}")
    print(f"  测试 #{case['id']}: {case['title']}")
    print(f"  分类: {case['category']}")
    print(f"  Prompt: {case['prompt'][:80]}")
    print("-" * 60)
    print(f"  【测试目标】{case['target']}")
    print(f"  【预期结果】{case['expected']}")
    print(f"  【观察重点】{case['focus']}")
    if case.get("note"):
        print(f"  【注意】{case['note']}")
    print("-" * 60)

    if not case["prompt"]:
        print("  ⚠️ 空 prompt 测试")

    print("\n  >>> 执行中...\n")
    try:
        result = spawn_subagent(case["prompt"])
        print("-" * 60)
        print(f"\n  返回结果:\n  {result}")
    except Exception as e:
        print("-" * 60)
        print(f"\n  异常: {type(e).__name__}: {e}")

    print(f"\n{'='*60}\n")


def main():
    print("Subagent 边界测试 — 手动调试工具\n")
    print_header()

    while True:
        try:
            query = input("test> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if query.lower() in ("q", "exit", "quit"):
            break

        if not query:
            continue

        if query.lower() == "list":
            list_cases()
            continue

        if query.lower() == "bounds":
            show_bounds()
            continue

        if query.lower().startswith("info "):
            show_case_info(query[5:].strip())
            continue

        # 匹配预设测试
        case = next((c for c in TEST_CASES if c["id"] == query), None)
        if case:
            run_case(case)
        else:
            # 自定义 prompt
            print(f"\n  >>> 自定义 prompt: {query[:60]}...\n")
            try:
                result = spawn_subagent(query)
                print(f"\n  返回结果:\n  {result}")
            except Exception as e:
                print(f"\n  异常: {type(e).__name__}: {e}")
            print()


if __name__ == "__main__":
    main()
