"""Generic thread-safe provider registry.

Shared bookkeeping (register / list / get / availability wrapper / test reset)
that was previously duplicated byte-for-byte across
``agent/web_search_registry.py`` and ``agent/browser_registry.py``. Each
subsystem subclasses :class:`ProviderRegistry` for its provider type and keeps
its own ``_resolve`` selection strategy — the two registries differ in
capability filtering (web search vs extract) and short-circuits (browser
``local``), so selection stays subclass-specific while the bookkeeping is
unified here.

Why only the bookkeeping is shared
----------------------------------
``_resolve`` differs enough between the two subsystems (web has a
``supports_search``/``supports_extract`` capability filter and a
single-eligible shortcut; browser has a ``local`` short-circuit and
deliberately omits the single-eligible rule) that forcing a single
parameterized resolver would be more complex than the duplication it removes.
The unified base class eliminates the bookkeeping drift (register validation,
``is_available`` exception wrapping, log levels) that actually caused
inconsistencies — browser warned at WARNING level while web logged at DEBUG,
and each had its own copy of the name-collision / re-register logic.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Generic, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderRegistry(Generic[T]):
    """Thread-safe map of named providers plus shared selection helpers.

    Subclasses:
      * pass ``log_unavailable_as_warning`` to ``__init__`` (browser warns,
        web stays at debug),
      * implement ``_resolve(configured, **kwargs)`` for subsystem-specific
        selection.

    The registry owns only bookkeeping — never selection policy.
    """

    def __init__(
        self,
        *,
        provider_label: str,
        log_unavailable_as_warning: bool = False,
    ) -> None:
        self._providers: Dict[str, T] = {}
        self._lock = threading.Lock()
        self._provider_label = provider_label
        self._log_unavailable_as_warning = log_unavailable_as_warning

    # ── registration / lookup (shared, identical across subsystems) ──────────

    def register_provider(self, provider: T, *, expected_type: type) -> None:
        """Register a provider, validating its type and ``.name``.

        Re-registration (same ``name``) overwrites the previous entry and logs
        at debug — makes hot-reload scenarios (tests, dev loops) behave
        predictably.
        """
        if not isinstance(provider, expected_type):
            raise TypeError(
                f"register_provider() expects a {expected_type.__name__} "
                f"instance, got {type(provider).__name__}"
            )
        name = provider.name  # type: ignore[attr-defined]
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"{expected_type.__name__}.name must be a non-empty string"
            )
        with self._lock:
            existing = self._providers.get(name)
            self._providers[name] = provider
        if existing is not None:
            logger.debug(
                "%s provider '%s' re-registered (was %r)",
                self._provider_label, name, type(existing).__name__,
            )
        else:
            logger.debug(
                "Registered %s provider '%s' (%s)",
                self._provider_label, name, type(provider).__name__,
            )

    def list_providers(self) -> List[T]:
        """Return all registered providers, sorted by ``.name``."""
        with self._lock:
            items = list(self._providers.values())
        return sorted(items, key=lambda p: p.name)  # type: ignore[attr-defined]

    def get_provider(self, name: str) -> Optional[T]:
        """Return the provider registered under *name*, or None."""
        if not isinstance(name, str):
            return None
        with self._lock:
            return self._providers.get(name.strip())

    def _snapshot(self) -> Dict[str, T]:
        """Atomically copy the provider map so callers iterate lock-free."""
        with self._lock:
            return dict(self._providers)

    def _is_available_safe(self, provider: T) -> bool:
        """Wrap ``is_available()`` so a buggy provider can't kill resolution."""
        name = getattr(provider, "name", "?")
        try:
            return bool(provider.is_available())  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            if self._log_unavailable_as_warning:
                logger.warning(
                    "%s provider %s.is_available() raised %s — treating as "
                    "unavailable",
                    self._provider_label, name, exc, exc_info=True,
                )
            else:
                logger.debug(
                    "%s provider %s.is_available() raised %s",
                    self._provider_label, name, exc,
                )
            return False

    def _reset_for_tests(self) -> None:
        """Clear the registry. **Test-only.**"""
        with self._lock:
            self._providers.clear()

    # ── selection (subsystem-specific — override in subclass) ────────────────

    def _resolve(self, configured: Optional[str], **kwargs: object) -> Optional[T]:
        """Return the active provider for this subsystem. Override in subclass."""
        raise NotImplementedError
