# Mini CC (Mini Claude Code) — Code Wiki

> 一个最小化的 Claude Code / Codex 风格 AI 编程助手（Agent），支持工具调用与多轮对话。

---

## 1. 项目整体架构

```
c:\AgentTest\
├── main.py          # 入口：Agent 主循环 & CLI 交互
├── llm.py           # LLM 调用层：封装 OpenAI 兼容 API
├── tools.py         # 工具层：工具函数定义 & Schema 声明
├── .env             # 环境变量：API Key / Base URL / 模型名
└── __pycache__/     # Python 字节码缓存
```

**架构分层：**

```
┌─────────────────────────────────┐
│           main.py               │  ← CLI 入口 & Agent 调度循环
│  (SYSTEM_PROMPT, run_agent,     │
│   main)                         │
└────────────┬────────────────────┘
             │ import
    ┌────────┴────────┐
    │                 │
┌───▼───┐      ┌─────▼─────┐
│ llm.py│      │ tools.py  │
│       │      │           │
│ call  │      │ TOOLS     │  ← 工具函数字典
│ _llm()│      │ TOOL_     │  ← OpenAI Function Calling
└───┬───┘      │ SCHEMAS   │    Schema 列表
    │          └───────────┘
    │
    ▼
 OpenAI 兼容 API (DashScope / 通义千问)
```

**数据流：**

```
用户输入 → run_agent() → call_llm(messages) → OpenAI API
                                                    │
                                      ┌─ 有 tool_calls? ─┐
                                      │ 是               │ 否
                                      ▼                  ▼
                                 执行工具           返回最终答案
                             追加 tool 消息         输出到终端
                             继续循环
```

---

## 2. 模块职责详解

### 2.1 `main.py` — Agent 主循环

| 要素 | 说明 |
|------|------|
| **职责** | CLI 入口、Agent 调度循环、工具调用分发 |
| **核心函数** | `run_agent()`, `main()` |

#### 关键常量

| 名称 | 类型 | 说明 |
|------|------|------|
| `DEBUG` | `bool` | 调试开关，默认 `False`。开启后输出详细日志 |
| `SYSTEM_PROMPT` | `str` | 系统提示词，定义 Agent 的行为准则（工具优先、不猜测、逐步推理） |

#### 关键函数

##### `log(msg: str) -> None`
- 条件日志输出函数，仅在 `DEBUG=True` 时打印。
- 格式：`[DEBUG] {msg}`

##### `run_agent(user_input: str) -> str`
- **Agent 核心调度循环**。
- 流程：
  1. 初始化 `messages` 列表，包含 `system` 和 `user` 消息。
  2. 进入无限循环：
     - 调用 `call_llm(messages)` 获取 LLM 响应。
     - 若响应包含 `tool_calls`：遍历执行每个工具调用，将结果以 `role: "tool"` 追加到消息列表，继续循环。
     - 若响应无 `tool_calls`：返回 `content` 作为最终答案。
- 异常处理：工具参数 JSON 解析失败时捕获异常，使用空字典 `{}` 作为参数；工具不存在时返回 `"未知工具: {name}"`；工具执行异常时返回 `"Tool execution error: {e}"`。

##### `main() -> None`
- CLI 交互入口。
- 循环读取用户输入，调用 `run_agent()` 并打印结果。
- 输入 `exit` 或 `quit` 退出。

---

### 2.2 `llm.py` — LLM 调用层

| 要素 | 说明 |
|------|------|
| **职责** | 封装 OpenAI 兼容 API 调用，管理客户端实例 |
| **核心函数** | `call_llm()` |
| **依赖** | `openai`, `python-dotenv` |

#### 关键变量

| 名称 | 类型 | 说明 |
|------|------|------|
| `client` | `openai.OpenAI` | 全局 OpenAI 客户端实例，在模块加载时初始化 |

#### 关键函数

##### `call_llm(messages: list) -> openai.types.chat.ChatCompletionMessage`
- 调用 LLM 并返回响应消息对象。
- 参数：
  - `model`：从环境变量 `OPENAI_MODEL` 读取，默认 `"qwen-plus"`。
  - `tools`：传入 `TOOL_SCHEMAS`，启用 Function Calling。
  - `tool_choice`：`"auto"`，由模型自主决定是否调用工具。
- 返回值：`response.choices[0].message`，包含 `content`（文本）和可选的 `tool_calls`（工具调用列表）。

---

### 2.3 `tools.py` — 工具层

| 要素 | 说明 |
|------|------|
| **职责** | 定义 Agent 可调用的工具函数及其 Schema |
| **导出** | `TOOLS` 字典、`TOOL_SCHEMAS` 列表 |

#### 工具函数

##### `list_dir(path: str = ".") -> str`
- **真实工具**。列出指定目录下的文件和子目录。
- 返回格式：每行 `[DIR] name` 或 `[FILE] name`。
- 错误处理：路径不存在、非目录、其他异常均有对应返回。

##### `read_file(path: str) -> str`
- **真实工具**。以 UTF-8 编码读取指定文件内容。
- 错误处理：文件不存在、非文件、其他异常均有对应返回。

##### `get_location() -> str`
- **模拟工具**。不调用系统定位，直接返回固定字符串 `"Los Angeles, California, USA"`。

##### `get_weather(location: str) -> str`
- **模拟工具**。不调用真实天气 API，根据传入的 `location` 匹配预设数据返回假天气。
- 预设有 LA（晴 26°C）、Toronto（多云 18°C）、Shanghai（小雨 24°C）三组数据。
- 未匹配时返回默认模板（晴 25°C）。

#### 工具注册

```python
TOOLS = {
    "list_dir": list_dir,
    "read_file": read_file,
    "get_location": get_location,
    "get_weather": get_weather,
}
```

#### Function Calling Schema

`TOOL_SCHEMAS` 是一个符合 OpenAI Function Calling 规范的列表，每个元素包含 `type: "function"` 和对应的 `function` 定义（`name`, `description`, `parameters`）。详见 [tools.py](file:///c:/AgentTest/tools.py#L69-L133)。

---

## 3. 依赖关系

### 外部依赖

| 包名 | 用途 |
|------|------|
| `openai` | OpenAI API 客户端，用于调用 LLM |
| `python-dotenv` | 从 `.env` 文件加载环境变量 |
| `pathlib` | 标准库，文件和目录操作 |
| `json` | 标准库，解析工具调用参数 |
| `os` | 标准库，读取环境变量 |

### 内部依赖

```
main.py ──→ llm.py (call_llm)
main.py ──→ tools.py (TOOLS)
llm.py  ──→ tools.py (TOOL_SCHEMAS)
```

---

## 4. 项目运行方式

### 4.1 环境要求

- Python 3.10+
- 有效的 OpenAI 兼容 API Key（项目使用阿里云 DashScope 上的通义千问模型）

### 4.2 安装

```bash
pip install openai python-dotenv
```

### 4.3 配置

编辑 `.env` 文件：

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=qwen3.6-plus
```

- `OPENAI_BASE_URL`：API 端点地址。兼容任何 OpenAI 格式的 API（如 DashScope、Ollama、vLLM 等）。
- `OPENAI_MODEL`：模型名称，默认 `qwen-plus`。

### 4.4 启动

```bash
python main.py
```

### 4.5 交互示例

```
Mini CC started. 输入 exit 退出。

User> 列出当前目录的文件

Assistant>
当前目录包含以下内容：
[FILE] .env
[DIR] __pycache__
[FILE] llm.py
[FILE] main.py
[FILE] tools.py

User> 查看一下洛杉矶的天气

Assistant>
洛杉矶当前天气：晴，气温 26°C，湿度 45%，微风。

User> exit
```

### 4.6 调试模式

将 `main.py` 中的 `DEBUG = False` 改为 `DEBUG = True` 即可看到详细日志：

```python
DEBUG = True
```

日志会输出每一步的循环数、消息数、工具调用详情和返回结果。

---

## 5. 扩展指南

### 添加新工具

1. 在 [tools.py](file:///c:/AgentTest/tools.py) 中定义工具函数。
2. 在 `TOOLS` 字典中注册函数。
3. 在 `TOOL_SCHEMAS` 列表中添加对应的 Function Calling Schema。

示例（添加一个计算器工具）：

```python
# 1. 定义函数
def calculate(expression: str) -> str:
    try:
        return str(eval(expression))
    except Exception as e:
        return f"计算错误: {e}"

# 2. 注册
TOOLS["calculate"] = calculate

# 3. 添加 Schema
{
    "type": "function",
    "function": {
        "name": "calculate",
        "description": "执行数学表达式计算",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 2+3*4",
                }
            },
            "required": ["expression"],
        },
    },
}
```

### 切换模型

修改 `.env` 中的 `OPENAI_MODEL`、`OPENAI_BASE_URL` 和 `OPENAI_API_KEY` 即可切换至任何 OpenAI 兼容的模型服务。