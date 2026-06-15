# Harness X 代码审查报告

- **审查日期**: 2026-06-14
- **审查范围**: 本次新增/修改代码（未提交工作树 + 已提交未推送 `main...HEAD`）
- **审查方法**: 7 角度并行 finder（3 correctness + 3 cleanup + 1 altitude）+ 1-vote recall-biased verify
- **关键上下文**: `web_chat.py` 定位为**测试工具**（测试当前项目效果），非生产代码 —— 这会改变部分发现的严重度

---

## 执行摘要

确认 10 个 correctness 问题 + 4 个结构性（altitude）问题：

- **5 个为核心/插件代码 bug**：与 web_chat 用途无关，应修。
- **5 个为 web_chat.py 特有**：在"测试工具"定位下重新评估，多数降级，但 **1 个（绕过 `agent_init`）反而升为高优先** —— 它使 web_chat 测不到真实项目效果，与其用途直接矛盾。
- **4 个结构性问题**（registry 重复、解析层分叉、凭证绕过 config 层）：建议在重新设计阶段统一处理。

---

## 1. 发现汇总

### 1A. 核心/插件代码 bug（与 web_chat 用途无关，建议尽快修）

| # | 文件:行 | 问题 | 严重度 | 状态 |
|---|---------|------|--------|------|
| 1 | `plugins/web/searxng/provider.py:117` | `float(r.get('score',0))` 在 SearXNG 返回 `score:null` 时 `float(None)` 抛 TypeError，排序未包 try/except，整个 `search()` 崩溃 | 高 | CONFIRMED |
| 2 | `plugins/memory/honcho/cli.py:192` | `list_profiles()` 返回 `['default']`（`List[str]`），但 honcho cli 迭代 `p.name` 当对象有 `.name` 属性 → `AttributeError` | 高 | CONFIRMED |
| 3 | `providers/base.py:208` | `fetch_models` 宽泛 `except Exception` 吞 `JSONDecodeError`：错误 base_url（parked domain 返 HTML 200）静默返回 None，回退空 fallback_models 无诊断 | 中 | CONFIRMED |
| 4 | `tools/web_tools.py:531` | `content = extract_content_or_reasoning(response)` 遮蔽函数 `content` 参数，重试耗尽 `return content` 返回 None/空串 | 中 | PLAUSIBLE |
| 5 | `tools/web_tools.py:209` | `_get_capability_backend` 在 `web.extract_backend:firecrawl` 缺凭证时回退到 `_get_backend()` 选 ddgs/searxng（仅搜索），返回误导错误，违反 registry docstring 的 "explicit config wins" 不变量 | 中 | PLAUSIBLE |

### 1B. web_chat.py 特有问题（测试工具定位下重新评估）

| # | 行 | 问题 | 生产严重度 | **测试工具下严重度** | 调整理由 |
|---|----|------|-----------|---------------------|----------|
| 6 | 47 | ~~绕过 `agent_init`~~ | 中 | **REFUTED（误报）** | 调查见下方修正 |
| 7 | 236 | `result.get("final_response", str(result))`：错误路径缺 `final_response` → 把整个统计 dict 渲染给用户 | 高 | **中** | 测试时错误被掩盖，影响判断 |
| 8 | 237 | `new_history = result.get('messages')` 存错误路径的内部 messages，毒化后续历史 | 高 | **中** | 连续测试时历史累积 |
| 9 | 36 | `_get_agent()` 双重检查锁定竞态（`if _agent is not None` 在锁外） | 中 | **低** | 单用户测试不触发 |
| 10 | 242 | `_sessions` 无界增长 + 无锁 | 中 | **低** | 短运行测试可接受 |

**修正 —— #6 经调查为误报（REFUTED）：**

原报告担心 web_chat "绕过 `agent_init`"，但调查显示：

- `__main__.py` 的 CLI 构造（72-76 行）与 web_chat **完全相同**，都是 `AIAgent(base_url, model, api_key)`，都自动经 `AIAgent.__init__ → init_agent`（run_agent.py:416-417 的 forwarder）。
- `enabled_toolsets`/`api_mode` 等均走默认，CLI 与 web_chat 行为一致。
- web_chat 反而**多了** `HARNESS_*` env var fallback（CLI 没有），更完整。

因此 "web_chat 测的 ≠ CLI 真实效果" 不成立，#6 降级为 REFUTED。web_chat 改造的真正价值在 **#7/#8（返回 shape 处理）**，已修复（错误路径不再 `str(dict)` 转储、不再持久化含重试标记的内部 messages）。

---

## 2. 重新设计建议

### 2A. web_chat 作为测试工具的重设计

**核心原则：web_chat 必须走与 CLI 完全一致的 agent 构造路径，否则测试无意义。**

1. ~~**复用 agent 构造逻辑**（解决 #6，最高优先）~~ → **#6 已证为误报**（见上方修正）：web_chat 与 CLI 构造本就一致，不存在"绕过 init_agent"。此项降为**可选的 DRY 改进**：若想消除两处构造重复、并让 CLI 也获得 `HARNESS_*` env var fallback（目前只有 web_chat 有），可抽 `build_default_agent()` helper 让两者共用；非紧急，留作未来清理。
2. **正确处理 `run_conversation` 返回**（解决 #7/#8）：读 `completed` / `error` / `final_response` 三字段，错误路径返回结构化错误信封；仅当 `completed=True` 时才把 messages 存入 history。
3. **明确标注非生产**：文件头注明"测试/演示工具，单用户、短运行"，避免后人当生产接口维护。或考虑：如果只是测试效果，直接用 `python __main__.py` CLI 即可，web_chat 的 HTML 包袱反而是额外维护负担。

### 2B. 项目层面重构（结构性，建议作为单独一轮工作）

| 建议 | 解决的问题 | 说明 |
|------|-----------|------|
| **抽取 `ProviderRegistry[T]` 基类** | `web_search_registry.py` 与 `browser_registry.py` ~90% 重复 | 抽到 `agent/provider_registry.py`，capability 过滤 + `_LEGACY_PREFERENCE` 作为策略参数。消除已发生的漂移（browser 用 `logger.warning`，web 用 `logger.debug`；web 有 single-eligible 快捷方式而 browser 注释性省略） |
| **统一 web 后端解析层** | `tools/web_tools.py` 三条并行解析路径（`_get_backend` / registry `_resolve` / `_wsp_get_provider` 回退） | 迁移只替换了一半解析层。删除 `_get_backend` 层，完全委托给 registry，消除每次调用可能返回不同 provider 的分叉（含 xai 在 `_get_backend` 存在但不在 `_LEGACY_PREFERENCE` 的不一致） |
| **插件凭证统一走 config 层** | `plugins/web/*`、`plugins/browser/*` 直接 `os.getenv` 绕过 `get_env_value`/`_env_value` | 导致 `hermes config set` 或 `~/.harness_x/.env` 设置的 API key 对插件不可见，`is_available()` 误报 False → 静默后端切换 |
| **`_LEGACY_PREFERENCE` 配置化** | 三处硬编码（两个 registry + web_tools）的 provider 偏好顺序 | 移到 config，避免三处分叉 |
| **`providers/base.py:fetch_models`** | 用 stdlib `urllib` 而非项目惯用的 `httpx`；宽泛 except | 换 `httpx`，收窄 except，对 `JSONDecodeError` 记 warning（解决 #3） |

---

## 3. 是否需要重新审核

**当前代码：不需要重审。** 本轮 7 角度 finder + verify 已覆盖现有代码的 correctness 与结构问题，发现已固化在本报告。

**重新设计/重构后：需要再审一轮。** 理由：

- 2B 的重构（registry 基类抽取、解析层统一）是结构性改动，易引入回归（capability 过滤迁移错误、`_resolve` 行为偏移、`_LEGACY_PREFERENCE` 配置化后的默认值兼容）。
- web_chat 复用 agent 构造后调用路径变化，需确认返回 shape 处理正确。
- 建议：重构完成、提交前，对改动文件跑一轮 `/code-review`（medium effort 即可，因范围明确）。

### 建议执行顺序

1. **立即**：修 1A 的 5 个核心 bug —— 小、独立、低风险。
2. **其次**：做 2A.1（web_chat 复用 agent 构造）—— 这是让测试有效的关键，也是 1B 中唯一高优先项。
3. **单独一轮**：2B 的结构重构，做完再审。

---

## 4. 2B 执行结果（2026-06-15，已完成）

5 项结构重构全部落地，逐项验证（项目无测试套件，以下用针对性烟测替代）：

| # | 项 | 落地 | 验证 |
|---|----|------|------|
| 2B-1 | 抽取 `ProviderRegistry[T]` 基类 | `browser_registry` 迁移到基类(2B 开始前 `web_search_registry` 已迁)。两 registry 共享 register/list/get/availability 簿记,各自保留 `_resolve` 策略 | 注册/解析/local 短路/显式配置/legacy 走查/类型校验 全过;`harness_cli.plugins` 调用方导入 OK |
| 2B-5 | `fetch_models` 换 httpx + 收窄 except | urllib→httpx(核心依赖,lazy 导入);**拆分请求相/解析相**:传输/HTTP 错误→debug,响应解析失败→warning("is base_url correct?"),末尾保留防御性 `except Exception` 兜底(契约=永不抛错) | mock server:ok/html200(#3 场景→warning)/404(→debug)/network/empty 全对;畸形 `ALL_PROXY=socks://` 环境→None+debug **不再误报"could not parse"** |
| 2B-3 | 插件凭证统一走 config 层 | 8 个 provider(exa/brave_free/tavily/parallel/web-firecrawl/browser_use/browserbase/browser-firecrawl)各加 `_env()` helper 复用 `get_env_value`,所有 `os.getenv`/`os.environ.get` 凭证读取路由过去(searxng 之前已迁) | monkeypatch `get_env_value` 模拟 `~/.harness_x/.env` 凭证 → `is_available()` 正确返回 True(正/负用例);不再误报 False→静默后端切换 |
| 2B-2 | 统一 web 解析层(删 `_get_backend` 三路分叉) | `_get_backend` 由 env-auto-detect 级联改为 registry 委托;`_get_capability_backend` = 显式配置直通 + registry 自动检测,**单一路径**;删除已死的 `_SEARCH_ONLY_BACKENDS` | 显式配置/自动检测/无可用 全场景:解析结果与 registry active provider 名一致;`web_search_tool`/`web_extract_tool`/`check_web_api_key` 行为保留 |
| 2B-4 | `_LEGACY_PREFERENCE` 配置化 | 2B-2 后第三处分叉已随 `_get_backend` 消失,仅剩 2 个 registry 常量。各自支持 `web.legacy_preference`/`browser.legacy_preference`(YAML list) 覆盖,默认值=原常量(零行为变更) | 默认未变/覆盖生效/非法值回退默认/`_resolve` 尊重覆盖 全过 |

### 行为变更（再审重点关注）

- **2B-2 — 显式 search-only 配置 extract**:原 `web.extract_backend: brave-free`(search-only)会静默回退到共享 backend;现返回该名 → dispatcher 给出 typed "search-only" 错误(更诚实,指引同一修复)。`web.backend: <search-only>` 行为不变(仍触发 typed 错误)。
- **2B-2 — 仅 search-only 可用时的 extract**:原给"X is search-only"错误;现给"No web extract provider configured"(同样指向 firecrawl/tavily/exa/parallel)。两者皆有效指引。
- **2B-5**:urllib→httpx 引入对环境代理的尊重(httpx 默认 `trust_env`)。畸形代理(如本环境的 `socks://`)→ 优雅降级为 None+debug,回退静态 `_PROVIDER_MODELS`,**不**误报 base_url 错误。

### 待办

- §3 建议的**再审一轮**:2B 属结构性改动,提交前建议对改动文件跑 `/code-review`(medium effort)。本报告已记录全部行为变更供其对焦。
- 提交:2B 涉及文件目前多为未跟踪(`agent/*_registry.py`、`plugins/`、`providers/`、`tools/web_tools.py`),需 `git add` 后一并提交。

