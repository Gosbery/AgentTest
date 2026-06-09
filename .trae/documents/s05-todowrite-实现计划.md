# s05 TodoWrite 实现计划

## 当前状态

已完成 s01-s04：Agent Loop + Tool Use + Permission + Hooks。

## 变更概述

在现有架构上新增 `todo_write` 工具和 nag reminder 机制，让 Agent 具备规划能力。

## 具体变更

### 1. tools.py - 新增 todo\_write 工具

**文件**: `c:\AgentTest\tools.py`

**变更**:

* 新增全局状态 `CURRENT_TODOS: list[dict] = []`

* 新增 `run_todo_write(todos: list) -> str` 函数

  * 接收带 status 的 todo 列表，保存在进程内存

  * 终端打印当前进度（pending / in\_progress / completed）

  * 返回更新摘要

* 在 `TOOLS` 字典注册: `"todo_write": run_todo_write`

* 在 `TOOL_SCHEMAS` 列表添加函数调用 schema

```python
# todo_write schema
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
}
```

### 2. main.py - 新增 nag reminder 机制

**文件**: `c:\AgentTest\main.py`

**变更**:

* 在 `run_agent` 函数中新增 `rounds_since_todo` 计数器

* 每次 `todo_write` 调用后重置计数器为 0

* 每次循环开始检查，连续 3 轮没调 `todo_write` 时注入提醒消息

* 更新 SYSTEM\_PROMPT，加入 "先计划再执行" 的引导语

```python
# 在 run_agent 循环内:
if rounds_since_todo >= 3:
    messages.append({
        "role": "user",
        "content": "<reminder>请更新你的 todo 列表，保持任务状态可见。</reminder>",
    })
    rounds_since_todo = 0

# 在 todo_write 执行后:
rounds_since_todo = 0
```

### 3. permissions.py - 允许 todo\_write

**文件**: `c:\AgentTest\permissions.py`

**变更**:

* 在 `PERMISSIONS` 字典添加 `"todo_write": "allow"`

### 4. hooks.py - 添加 todo\_write 日志

**文件**: `c:\AgentTest\hooks.py`

**变更**:

* 在 `after_tool` 中为 `todo_write` 添加格式化输出

* 打印当前任务进度摘要

## 测试步骤

1. 运行 `python main.py`
2. 输入复杂任务，例如: "把所有 Python 文件改成 snake\_case 命名"
3. 观察:

   * 第一次工具调用是否是 `todo_write`

   * TODO 列表是否正确列出步骤

   * 执行过程中状态是否从 pending → in\_progress → completed

   * 如果 Agent 忘记更新 todo，3 轮后是否收到提醒

## 假设和决策

* 使用进程内存保存 todo（退出后清空），与教学版一致

* 不引入文件持久化（那是 s12 Task System 的内容）

* nag reminder 固定 3 轮，与教学版一致

* 不引入 activeForm 字段（UI spinner 用途，不需要）

