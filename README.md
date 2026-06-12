# Harness X

Core AI agent framework，从 [hermes-agent](https://github.com/NousResearch/hermes-agent) 提取的核心模块。

剥离了消息网关（Telegram/Discord/Slack 等）、插件系统、技能包、前端 UI、TUI、桌面应用和第三方平台集成（Modal/Daytona/Singularity），只保留 **对话循环、LLM 适配、工具调度、子 Agent 委派** 等核心能力。

## 架构

```
harness_x/
├── __main__.py              # CLI 入口 (python -m harness_x)
├── run_agent.py             # AIAgent 核心：对话循环 + 工具调用
├── model_tools.py           # 工具编排层，桥接 tools/registry
├── toolsets.py              # 工具集定义（按平台分组）
├── toolset_distributions.py # 工具集分发配置
├── harness_constants.py     # 全局常量、HERMES_HOME 路径管理
├── harness_bootstrap.py     # Windows UTF-8 引导（POSIX 无操作）
├── harness_logging.py       # 日志配置
├── harness_state.py         # SQLite 会话存储 + FTS5 全文搜索
├── harness_time.py          # 时间工具
├── utils.py                 # 通用工具函数
│
├── agent/                   # LLM 适配器 & Agent 内部模块
│   ├── anthropic_adapter.py     # Anthropic Claude
│   ├── bedrock_adapter.py       # AWS Bedrock
│   ├── gemini_native_adapter.py # Google Gemini
│   ├── codex_responses_adapter.py  # OpenAI Codex
│   ├── prompt_builder.py        # 系统提示词构建
│   ├── context_compressor.py    # 上下文压缩
│   ├── memory_manager.py        # 跨会话记忆
│   ├── conversation_loop.py     # 对话循环抽象
│   ├── tool_executor.py         # 工具执行器
│   ├── display.py               # Rich 输出渲染
│   └── ...                      # 60+ 内部模块
│
├── tools/                   # 40+ 工具实现（自注册模式）
│   ├── registry.py              # 工具注册表（核心）
│   ├── file_tools.py            # 文件读写搜索
│   ├── terminal_tool.py         # 终端/Shell 执行
│   ├── delegate_tool.py         # 子 Agent 委派
│   ├── memory_tool.py           # 记忆读写
│   ├── todo_tool.py             # 任务管理
│   ├── clarify_tool.py          # 澄清追问
│   ├── environments/            # 终端后端（local/docker/ssh）
│   └── ...
│
├── harness_cli/             # CLI 基础设施
│   ├── config.py                # 配置加载（YAML + .env）
│   ├── auth.py                  # API Key 认证
│   ├── models.py                # 模型元数据
│   ├── plugins.py               # 插件加载器（保留接口）
│   └── ...
│
└── gateway/                 # 网关存根（已剥离具体平台适配器）
    ├── __init__.py
    ├── platform_registry.py
    ├── session_context.py
    └── status.py
```

## 核心流程

```
用户输入 → AIAgent.run_conversation()
  → LLM API 调用（OpenAI/Anthropic/Gemini/Bedrock）
  → 解析 tool_calls → model_tools.handle_function_call()
  → tools/registry.py 分发到具体工具
  → 工具结果追加到消息历史
  → 循环直到 LLM 不再调用工具
  → 返回最终文本响应
```

## 快速开始

### 安装

```bash
# 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 安装核心依赖
pip install -e .

# 可选：安装 Anthropic 支持
pip install -e ".[anthropic]"
```

### 配置

```bash
# 创建配置文件
mkdir -p ~/.harness_x
cat > ~/.harness_x/config.yaml << 'EOF'
model: gpt-4o
base_url: https://api.openai.com/v1
EOF

# API Key 通过环境变量或 .env 文件设置
echo "OPENAI_API_KEY=sk-..." > ~/.harness_x/.env
```

### 运行

```bash
# 交互式对话
python __main__.py

# 单次查询
python __main__.py chat -q "解释 Python GIL"

# 诊断环境
python __main__.py doctor

# 查看帮助
python __main__.py help
```

### 作为库使用

```python
from run_agent import AIAgent

agent = AIAgent(
    base_url="https://api.openai.com/v1",
    model="gpt-4o",
    api_key="sk-...",
)

response = agent.run_conversation("用 Python 写一个快速排序")
print(response)
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `HARNESS_HOME` | 数据目录 | `~/.harness_x` |
| `HARNESS_API_KEY` | 默认 API Key | — |
| `HARNESS_BASE_URL` | 默认 API URL | — |
| `HARNESS_MODEL` | 默认模型名 | `gpt-4o` |
| `HERMES_HOME` | 兼容旧变量（HARNESS_* 优先） | — |

## 与 hermes-agent 的关系

| 维度 | hermes-agent | harness_x |
|------|-------------|-----------|
| 定位 | 全功能 AI Agent 平台 | 精简核心框架 |
| 消息网关 | 20+ 平台适配器 | 已剥离（仅保留 stub） |
| 插件系统 | 完整插件生态 | 保留加载接口 |
| 技能包 | 内置 + 可选 | 未包含 |
| 前端 | Web Dashboard + TUI + Desktop | 未包含 |
| 第三方平台 | Modal/Daytona/Singularity SSH | 已剔除 |
| 代码量 | ~200k LOC | ~30k LOC |

## License

MIT — 与 hermes-agent 保持一致。
