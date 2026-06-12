# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Harness X — a core AI agent framework extracted from [hermes-agent](https://github.com/NousResearch/hermes-agent). Provides the conversation loop, LLM adapters, tool dispatch, and subagent delegation without the messaging gateways, plugin ecosystem, skills, or frontends of the original platform.

## Commands

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .                      # Core dependencies
pip install -e ".[anthropic]"         # Optional: Anthropic Claude support
pip install -e ".[dev]"               # Optional: pytest, ruff

# Run
python __main__.py                    # Interactive chat
python __main__.py chat -q "query"   # One-shot query
python __main__.py doctor             # Diagnose setup issues

# Lint (dev dependency)
ruff check .

# Test (no tests exist yet)
pytest
```

Configuration lives in `~/.harness_x/config.yaml` (model, base_url, etc.) and `~/.harness_x/.env` (API keys). Environment variables `HARNESS_HOME`, `HARNESS_API_KEY`, `HARNESS_BASE_URL`, `HARNESS_MODEL` override config. Legacy `HERMES_*` env vars still work but `HARNESS_*` takes priority.

## Architecture

### Core Loop

```
User input → AIAgent.run_conversation()  (run_agent.py)
  → LLM API call (via provider adapter/transport)
  → Parse tool_calls → model_tools.handle_function_call()
  → tools/registry.py dispatches to tool handler
  → Tool result appended to message history
  → Loop until LLM stops calling tools
  → Return final text response
```

### Key Modules (by role)

**`run_agent.py`** — `AIAgent` class: the central orchestrator. Holds conversation state, LLM client, tool definitions, and drives the turn loop. ~6k lines. The `run_conversation` body is extracted to `agent/conversation_loop.py`.

**`model_tools.py`** — Thin orchestration over the tool registry. Public API: `get_tool_definitions()`, `handle_function_call()`, toolset queries. Triggers tool discovery by importing all `tools/*.py` modules. Bridges async tool handlers to sync callers via persistent event loops.

**`tools/registry.py`** — Central tool registry. Each tool file calls `registry.register()` at module level to declare its schema, handler, toolset membership, and availability check. `discover_builtin_tools()` AST-scans `tools/*.py` for `registry.register()` calls, imports only those modules.

**`agent/conversation_loop.py`** — The extracted `run_conversation` body: model call → tool dispatch → retries → fallbacks → compression → post-turn hooks.

**`agent/transports/`** — Provider transport layer (auto-registering). Each transport (`anthropic.py`, `chat_completions.py`, `codex.py`, `bedrock.py`) converts between internal OpenAI-format messages and provider-native format. `get_transport(api_mode)` returns the right one. Transports normalize all responses to `NormalizedResponse`.

### Provider Adapters

Provider-specific logic lives in `agent/` top-level files:
- `anthropic_adapter.py` — Claude Messages API (lazy SDK import, supports API keys + OAuth + Claude Code credentials)
- `bedrock_adapter.py` — AWS Bedrock
- `gemini_native_adapter.py` — Google Gemini
- `codex_responses_adapter.py` — OpenAI Codex
- `gemini_cloudcode_adapter.py`, `azure_identity_adapter.py` — additional providers

All adapters lazy-import their SDKs (they're optional dependencies that add ~200ms+ to startup).

### Tool System

Tools self-register at import time via `registry.register()`. Each tool file defines:
- JSON schema for the tool's parameters
- Handler function (sync or async)
- Toolset membership (e.g., "core", "web", "browser")
- Availability check (e.g., checks for optional dependencies)

Key tools: `file_tools.py` (read/write/search), `terminal_tool.py` (local/docker/modal/ssh execution), `delegate_tool.py` (subagent spawning with isolated context), `memory_tool.py`, `todo_tool.py`, `clarify_tool.py`.

Terminal tool supports multiple backends via `tools/environments/` (`local.py`, `docker.py`, `ssh.py`, `modal.py`, etc.).

### Subagent Delegation (`delegate_tool.py`)

Spawns child `AIAgent` instances with isolated conversation context, restricted toolsets, and own terminal sessions. Blocked tools: `delegate_task` (no recursion), `clarify` (no user interaction), `memory` (no shared memory writes). Supports parallel batch mode via `ThreadPoolExecutor`.

### State Persistence (`harness_state.py`)

SQLite with WAL mode + FTS5 full-text search. Stores session metadata, full message history, model config. Falls back to DELETE journal mode on NFS/SMB where WAL is incompatible. Session compression triggers parent/child chain splitting.

### Toolset System (`toolsets.py`)

Groups tools into named sets (e.g., `_HARNESS_CORE_TOOLS` defines the default CLI toolset). Toolsets compose from individual tools or other toolsets. `toolset_distributions.py` configures per-platform toolset bundles.

### Context Management

- `agent/context_compressor.py` — Automatic context window compression when conversations exceed model limits. Uses an auxiliary (cheap/fast) model to summarize middle turns while protecting head and tail context.
- `agent/memory_manager.py` — Orchestrates memory providers. Only one external plugin provider allowed at a time. Manages pre-turn prefetch and post-turn sync.
- `agent/prompt_builder.py` — Assembles system prompt from identity, platform hints, skills index, context files. Includes threat scanning for context files.

### Configuration (`harness_cli/config.py`)

YAML-based config at `~/.harness_x/config.yaml`. Supports `config edit`, `config set`, and setup wizard. Corrupt configs are backed up with `.bak` suffix rather than silently overwritten.

## Conventions

- **Lazy SDK imports**: Provider SDKs (anthropic, google.genai) are imported lazily via accessors, not at module top-level. They're optional dependencies that significantly slow startup.
- **Import chain safety**: `tools/registry.py` has no imports from `model_tools` or tool files. Tool files import from `registry`. `model_tools` imports from both. This prevents circular imports.
- **Thread-local event loops**: `model_tools.py` maintains persistent asyncio event loops (main thread + per-worker) to avoid "Event loop is closed" errors with cached httpx/AsyncOpenAI clients.
- **`_ra()` indirection**: Symbols that tests patch on `run_agent` are resolved through `_ra()` (re-imports `run_agent`) so monkey-patching works with extracted modules.
- **HERMES → HARNESS migration**: All `HERMES_*` env vars have `HARNESS_*` equivalents. `HARNESS_*` wins. `harness_constants.getenv()` handles priority automatically.
- **Self-registering tools**: New tools in `tools/` call `registry.register()` at module level. They're auto-discovered by AST scanning for that call pattern.
- **Self-registering transports**: New transports in `agent/transports/` subclass `ProviderTransport` and call `register_transport()` at module level. They're auto-discovered by `__init__.py`.
