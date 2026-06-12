"""Lightweight stub for gateway.platform_registry.

The full gateway maintains a registry of active platform adapters (Telegram,
Discord, Slack, etc.). In harness_x (no messaging platforms), the registry is
always empty.

Called by: agent/system_prompt.py, hermes_cli/plugins.py, toolsets.py
"""

from typing import Any, Dict, List, Optional


class PlatformEntry:
    """Stub — represents a registered messaging platform."""
    def __init__(self, name: str = "unknown", platform_type: str = "unknown"):
        self.name = name
        self.platform_type = platform_type


class _PlatformRegistry:
    """Stub registry — always empty, no platforms registered."""

    def get_platforms(self) -> List[PlatformEntry]:
        return []

    def get_platform(self, name: str) -> Optional[PlatformEntry]:
        return None

    def is_registered(self, name: str) -> bool:
        return False

    def broadcast(self, *args, **kwargs) -> None:
        pass


platform_registry = _PlatformRegistry()
