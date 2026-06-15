"""
Web Search Provider Registry
============================

Central map of registered web providers. Populated by plugins at import-time
via :meth:`PluginContext.register_web_search_provider`; consumed by the
``web_search`` and ``web_extract`` tool wrappers in :mod:`tools.web_tools` to
dispatch each call to the active backend.

The shared register/list/get/availability bookkeeping lives on the generic
:class:`agent.provider_registry.ProviderRegistry` base; this module keeps only
the web-specific selection policy (capability filter + legacy preference walk).

Active selection
----------------

The active provider is chosen by configuration with this precedence:

1. ``web.search_backend`` / ``web.extract_backend``
   (per-capability override).
2. ``web.backend`` (shared fallback).
3. If exactly one capability-eligible provider is registered AND available,
   use it.
4. Legacy preference order — ``firecrawl`` → ``parallel`` → ``tavily`` →
   ``exa`` → ``searxng`` → ``brave-free`` → ``ddgs`` — filtered by
   availability. Matches the historic ``tools.web_tools._get_backend()``
   candidate order so installs that never set a config key keep landing
   on the same provider they did before the plugin migration.
5. Otherwise ``None`` — the tool surfaces a helpful error pointing at
   ``hermes tools``.

The capability filter (``supports_search`` / ``supports_extract``) is
applied at every step so a search-only provider (``brave-free``)
configured as ``web.extract_backend`` correctly falls through to an
extract-capable backend.
"""

from __future__ import annotations

import logging
from typing import Optional

from agent.provider_registry import ProviderRegistry
from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


class _WebSearchRegistry(ProviderRegistry[WebSearchProvider]):
    """Web search/extract registry with capability-aware selection.

    ``log_unavailable_as_warning`` is False (matching the original module,
    which logged ``is_available`` failures at debug) — a web backend whose
    probe raises is a routine fallback, not a warning-worthy event.
    """

    def __init__(self) -> None:
        super().__init__(provider_label="Web", log_unavailable_as_warning=False)

    def _resolve(
        self,
        configured: Optional[str],
        *,
        capability: str,
    ) -> Optional[WebSearchProvider]:
        """Resolve the active provider for a capability ("search" | "extract").

        Resolution rules (in order):

        1. **Explicit config wins, ignoring availability.** If
           ``web.{capability}_backend`` or ``web.backend`` names a registered
           provider that supports *capability*, return it even if its
           :meth:`is_available` returns False — the dispatcher will surface a
           precise "X_API_KEY is not set" error to the user instead of silently
           routing somewhere else. Matches legacy
           :func:`tools.web_tools._get_backend` behavior for configured names.

        2. **Single-provider shortcut.** When only one registered provider
           supports *capability* AND ``is_available()`` reports True, return it.

        3. **Legacy preference walk, filtered by availability.** Walk the
           :data:`_LEGACY_PREFERENCE` order (firecrawl → parallel → tavily →
           exa → searxng → brave-free → ddgs) looking for a provider whose
           ``supports_<capability>()`` is True AND whose ``is_available()`` is
           True. Matches the historic ``tools.web_tools._get_backend()``
           candidate order so users with credentials but no explicit config
           key keep landing on the same provider as pre-migration. This is
           the path that fires when no config key is set — pick the
           highest-priority backend the user actually has credentials for.

        Returns None when no provider is configured AND no available provider
        matches the legacy preference; the dispatcher then returns a "set up a
        provider" error to the user.
        """
        snapshot = self._snapshot()

        def _capable(p: WebSearchProvider) -> bool:
            if capability == "search":
                return bool(p.supports_search())
            if capability == "extract":
                return bool(p.supports_extract())
            return False

        # 1. Explicit config wins — return regardless of is_available() so the
        #    user gets a precise downstream error message rather than a silent
        #    backend switch. Matches _get_backend() in web_tools.py.
        if configured:
            provider = snapshot.get(configured)
            if provider is not None and _capable(provider):
                return provider
            if provider is None:
                logger.debug(
                    "web backend '%s' configured but not registered; falling back",
                    configured,
                )
            else:
                logger.debug(
                    "web backend '%s' configured but does not support '%s'; falling back",
                    configured, capability,
                )

        # 2. + 3. Fallback path — filter by availability so we don't surface
        # a provider the user has no credentials for. Without this filter,
        # a registered-but-unconfigured provider could end up "active" on
        # a fresh install with no API keys at all.
        eligible = [
            p for p in snapshot.values()
            if _capable(p) and self._is_available_safe(p)
        ]
        if len(eligible) == 1:
            return eligible[0]

        for legacy in _legacy_preference():
            provider = snapshot.get(legacy)
            if (
                provider is not None
                and _capable(provider)
                and self._is_available_safe(provider)
            ):
                return provider

        return None


# Legacy preference order — preserves behaviour for users who set no
# ``web.backend`` / ``web.<capability>_backend`` config key at all. Matches
# the historic candidate order in :func:`tools.web_tools._get_backend`
# (paid providers first so existing paid setups don't get downgraded to
# a free tier on upgrade). Filtered by ``is_available()`` at walk time so
# we don't surface a provider the user has no credentials for.
_LEGACY_PREFERENCE = (
    "firecrawl",
    "parallel",
    "tavily",
    "exa",
    "searxng",
    "brave-free",
    "ddgs",
)


# Module-level singleton — all public functions below delegate to it so
# existing callers (PluginContext.register_web_search_provider, tools.web_tools)
# keep the same import surface.
_registry = _WebSearchRegistry()


# ---------------------------------------------------------------------------
# Public module API (unchanged surface, delegates to the singleton)
# ---------------------------------------------------------------------------

def register_provider(provider: WebSearchProvider) -> None:
    """Register a web search/extract provider.

    Re-registration (same ``name``) overwrites the previous entry and logs
    a debug message — makes hot-reload scenarios (tests, dev loops) behave
    predictably.
    """
    _registry.register_provider(provider, expected_type=WebSearchProvider)


def list_providers():  # type: ignore[no-untyped-def]
    """Return all registered providers, sorted by name."""
    return _registry.list_providers()


def get_provider(name: str) -> Optional[WebSearchProvider]:
    """Return the provider registered under *name*, or None."""
    return _registry.get_provider(name)


def _reset_for_tests() -> None:
    """Clear the registry. **Test-only.**"""
    _registry._reset_for_tests()


# ---------------------------------------------------------------------------
# Active-provider resolution
# ---------------------------------------------------------------------------

def _read_config_key(*path: str) -> Optional[str]:
    """Resolve a dotted config key from ``config.yaml``. Returns None on miss."""
    try:
        from harness_cli.config import load_config

        cfg = load_config()
        cur = cfg
        for segment in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(segment)
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    except Exception as exc:
        logger.debug("Could not read config %s: %s", ".".join(path), exc)
    return None


def _read_config_list(*path: str) -> Optional[tuple]:
    """Resolve a list-of-strings config key from ``config.yaml``.

    Returns a lowercased, stripped tuple, or None on miss / non-list /
    read error. Used for the overridable ``web.legacy_preference`` list.
    """
    try:
        from harness_cli.config import load_config

        cfg = load_config()
        cur = cfg
        for segment in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(segment)
        if isinstance(cur, (list, tuple)):
            cleaned = tuple(
                str(x).strip().lower() for x in cur if str(x).strip()
            )
            return cleaned if cleaned else None
    except Exception as exc:
        logger.debug("Could not read config %s: %s", ".".join(path), exc)
    return None


def _legacy_preference() -> tuple:
    """Legacy auto-detect order for web providers.

    Overridable via ``web.legacy_preference`` (a YAML list of provider names)
    in ``config.yaml``; defaults to :data:`_LEGACY_PREFERENCE`. The override
    lets a user reorder (or narrow) auto-detection without editing code, while
    the module constant remains the documented default so existing installs
    with no config key keep landing on the same provider.
    """
    override = _read_config_list("web", "legacy_preference")
    return override if override else _LEGACY_PREFERENCE


def get_active_search_provider() -> Optional[WebSearchProvider]:
    """Resolve the currently-active web search provider.

    Reads ``web.search_backend`` (preferred) or ``web.backend`` (shared
    fallback) from config.yaml; falls back per the module docstring.
    """
    explicit = _read_config_key("web", "search_backend") or _read_config_key("web", "backend")
    return _registry._resolve(explicit, capability="search")


def get_active_extract_provider() -> Optional[WebSearchProvider]:
    """Resolve the currently-active web extract provider.

    Reads ``web.extract_backend`` (preferred) or ``web.backend`` (shared
    fallback) from config.yaml; falls back per the module docstring.
    """
    explicit = _read_config_key("web", "extract_backend") or _read_config_key("web", "backend")
    return _registry._resolve(explicit, capability="extract")
