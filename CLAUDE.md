# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Harness X — a core AI agent framework extracted from [hermes-agent](https://github.com/NousResearch/hermes-agent). Provides the conversation loop, LLM adapters, tool dispatch, subagent delegation, and a self-registering **plugin/provider** system. The messaging gateways (Telegram/Discord/Slack), skills, dashboards, TUI, and desktop app of the original platform were stripped, but the **plugin loader and the backend-provider registries were retained** — so `plugins/`, `providers/`, and the `agent/*_registry.py` modules are first-class, not vestigial.

## Commands

```bash
# Setup
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e .                      # Core dependencies
pip install -e ".[anthropic]"         # Optional: Anthropic Claude support
pip install -e ".[dev]"               # Optional: pytest, ruff

# Run (CLI — subcommands live in __main__.py: chat, doctor, help)
python __main__.py                    # Interactive chat
python __main__.py chat -q "query"   # One-shot query
python __main__.py doctor             # Diagnose setup issues

# Minimal web chat (standalone HTTP server, lazy AIAgent singleton)
python web_chat.py                    # http://127.0.0.1:8080
python web_chat.py --port 3000

# Lint (dev dependency)
ruff check .

# Test (no tests exist yet)
pytest
```

The CLI's only subcommands are `chat`, `doctor`, and `help` — there is no `config`/`tools`/`plugins` CLI surface in `__main__.py`. (`harness_cli/config.py` exposes `config edit` / `config set` as functions called by the setup wizard, not as CLI verbs.) `web_chat.py` is a separate entry point that drives the same `AIAgent.run_conversation()` as the CLI — it shares the exact conversation path, not a parallel one.

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

### Provider Adapters & Profiles

Two complementary layers describe each inference provider:

- **`agent/<provider>_adapter.py`** — SDK-specific glue (Claude Messages API, Bedrock, Gemini, Codex, etc.). Lazy-import their SDKs (optional deps that add ~200ms+ to startup). Handles auth, client construction, streaming.
- **`providers/base.py` → `ProviderProfile`** — A *declarative* dataclass describing one provider in one place (auth, endpoints, env vars, model catalog, client/request quirks). Profiles do NOT own client construction or streaming — those stay on `AIAgent`. The transport reads `profile.prepare_messages()`, `profile.build_extra_body()`, `profile.build_api_kwargs_extras()`, `profile.get_max_tokens()` instead of receiving 20+ boolean flags.

Profiles live as plugins under `plugins/model-providers/<name>/` (28 bundled: anthropic, gemini, deepseek, openrouter, xai, qwen, kimi, …) and `$HERMES_HOME/plugins/model-providers/<name>/` (user overrides, last-writer-wins). The registry in `providers/__init__.py` is **lazy** — first `get_provider_profile()`/`list_providers()` call scans both locations. See `providers/README.md` for the full list of downstream layers that read from profiles.

### Plugin System (`harness_cli/plugins.py`)

Discovers, loads, and invokes plugins from four sources (later sources override earlier on name collision):

1. **Bundled** — `plugins/<name>/` (shipped with the repo)
2. **User** — `~/.harness_x/plugins/<name>/`
3. **Project** — `./.hermes/plugins/<name>/` (opt-in via `HERMES_ENABLE_PROJECT_PLUGINS`)
4. **Pip** — packages exposing the `hermes_agent.plugins` entry-point group

Each directory plugin has a `plugin.yaml` manifest + `__init__.py` with a `register(ctx)` function. `ctx` is a `PluginContext` facade exposing `register_tool`, `register_hook`, `register_middleware`, `register_browser_provider`, `register_web_search_provider`, `register_context_engine`, `register_cli_command`, `register_command` (slash), etc.

**Manifest `kind`** gates loading behavior — this is the part most likely to trip you up:

| kind | loading |
|------|---------|
| `standalone` (default) | Opt-in via `plugins.enabled` in config |
| `backend` | Bundled auto-loads; user-installed still gated by `plugins.enabled` |
| `platform` | Gateway adapter; bundled auto-loads |
| `exclusive` | Own discovery path (e.g. `memory` providers, selected via `<category>.provider`). General scanner records but does **not** import. |
| `model-provider` | Handled by `providers/__init__.py` lazy discovery, **not** the general loader. Scanner records but does **not** import — a second import would create duplicate `ProviderProfile` instances and break override semantics. |

Bundled plugins today: `context_engine`, `memory`, `model-providers`, `observability`, `browser` (browserbase/browser_use/firecrawl), `web` (7 search engines + parallel aggregator), `security-guidance`, `disk-cleanup`. Third-party SDKs are lazy-imported inside each plugin and degrade to `FeatureUnavailable` when absent. `HERMES_PLUGINS_DEBUG=1` surfaces verbose discovery logging.

### Provider Registries & Resolution (`agent/*_registry.py`)

The web and browser subsystems follow the same pattern: plugins register concrete backends into a central registry at import time; a tool wrapper resolves the *active* one per call.

- **`agent/web_search_registry.py`** — search/extract backends (consumed by `tools/web_tools.py`). Capability-aware: each provider declares `supports_search()`/`supports_extract()`.
- **`agent/browser_registry.py`** — cloud browser backends (consumed by the `browser_*` tools, which now live in plugins — there is **no `tools/browser_tool.py`**).

Both registries share the same **resolution precedence** (encoded in `_resolve()`):

1. **Explicit config wins, ignoring availability** — `web.search_backend`/`web.backend`/`browser.cloud_provider` in `config.yaml` returns the named provider *even if `is_available()` is False*, so the user gets a typed "X_API_KEY not set" error instead of a silent backend switch.
2. **Single-eligible shortcut** (web only) — exactly one registered, capability-matching, available provider.
3. **Legacy preference walk, filtered by availability** — hardcoded order (`_LEGACY_PREFERENCE`) preserving pre-migration auto-detect behavior. Browser notably does **not** include `firecrawl` here, because `FIRECRAWL_API_KEY` is shared with the web-extract plugin and must not silently route to a paid cloud browser.

When changing resolution logic, update both the `_resolve()` docstring and `_LEGACY_PREFERENCE` — they are the spec. `_reset_for_tests()` clears each registry.

### Tool System

Tools self-register at import time via `registry.register()`. Each tool file defines:
- JSON schema for the tool's parameters
- Handler function (sync or async)
- Toolset membership (e.g., "core", "web", "browser")
- Availability check (e.g., checks for optional dependencies)

Key tools: `file_tools.py` (read/write/search), `terminal_tool.py` (local/docker/modal/ssh execution), `delegate_tool.py` (subagent spawning with isolated context), `memory_tool.py`, `todo_tool.py`, `clarify_tool.py`. `tools/web_tools.py` is the web search/extract wrapper that delegates to the active registry backend; it re-exports Firecrawl helpers from `plugins/web/firecrawl/provider.py` so test patches against `tools.web_tools.*` keep working.

Terminal tool supports multiple backends via `tools/environments/` (`local.py`, `docker.py`, `ssh.py`, `modal.py`, etc.).

### Subagent Delegation (`delegate_tool.py`)

Spawns child `AIAgent` instances with isolated conversation context, restricted toolsets, and own terminal sessions. Blocked tools: `delegate_task` (no recursion), `clarify` (no user interaction), `memory` (no shared memory writes). Supports parallel batch mode via `ThreadPoolExecutor`.

### State Persistence (`harness_state.py`)

SQLite with WAL mode + FTS5 full-text search. Stores session metadata, full message history, model config. Falls back to DELETE journal mode on NFS/SMB where WAL is incompatible. Session compression triggers parent/child chain splitting.

### Toolset System (`toolsets.py`)

Groups tools into named sets (e.g., `_HARNESS_CORE_TOOLS` defines the default CLI toolset). Toolsets compose from individual tools or other toolsets. `toolset_distributions.py` configures per-platform toolset bundles.

### Context Management

- `agent/context_compressor.py` — Automatic context window compression when conversations exceed model limits. Uses an auxiliary (cheap/fast) model to summarize middle turns while protecting head and tail context. A plugin can replace this via `ctx.register_context_engine()` (only one allowed).
- `agent/memory_manager.py` — Orchestrates memory providers. Only one external plugin provider allowed at a time. Manages pre-turn prefetch and post-turn sync.
- `agent/prompt_builder.py` — Assembles system prompt from identity, platform hints, skills index, context files. Includes threat scanning for context files.

### Configuration (`harness_cli/config.py`)

YAML-based config at `~/.harness_x/config.yaml`. Supports `config edit`, `config set`, and setup wizard. Corrupt configs are backed up with `.bak` suffix rather than silently overwritten. Plugin backend selection keys (`web.backend`, `browser.cloud_provider`, `plugins.enabled`, `memory.provider`, etc.) all live here.

### Minimal Stubs (intentional — do not "fix")

These modules are deliberately tiny placeholders retained because migrated plugins import them. Porting the full hermes-agent subsystem behind them is out of scope:

- **`agent/models_dev.py`** — `lookup_models_dev_context()` returns `None` so callers fall through to heuristic context-length defaults.
- **`harness_cli/profiles.py`** — single-profile stub (`list_profiles()` → `["default"]`) satisfying the `memory` plugin's import.

## Conventions

- **Lazy SDK imports**: Provider SDKs (anthropic, google.genai) are imported lazily via accessors, not at module top-level. They're optional dependencies that significantly slow startup. Plugin SDKs follow the same rule and degrade to `FeatureUnavailable`.
- **Import chain safety**: `tools/registry.py` has no imports from `model_tools` or tool files. Tool files import from `registry`. `model_tools` imports from both. This prevents circular imports.
- **Thread-local event loops**: `model_tools.py` maintains persistent asyncio event loops (main thread + per-worker) to avoid "Event loop is closed" errors with cached httpx/AsyncOpenAI clients.
- **`_ra()` indirection**: Symbols that tests patch on `run_agent` are resolved through `_ra()` (re-imports `run_agent`) so monkey-patching works with extracted modules.
- **HERMES → HARNESS migration**: All `HERMES_*` env vars have `HARNESS_*` equivalents. `HARNESS_*` wins. `harness_constants.getenv()` handles priority automatically.
- **Self-registering tools**: New tools in `tools/` call `registry.register()` at module level. They're auto-discovered by AST scanning for that call pattern.
- **Self-registering transports**: New transports in `agent/transports/` subclass `ProviderTransport` and call `register_transport()` at module level. They're auto-discovered by `__init__.py`.
- **Self-registering providers**: Browser/web backends register via `PluginContext.register_*_provider()` → `agent/*_registry.register_provider()` at plugin import time; provider *profiles* register via `providers.register_provider()`. Both are lazy-discovered.
