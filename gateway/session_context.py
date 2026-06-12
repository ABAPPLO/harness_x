"""Lightweight stub for gateway.session_context.

The full gateway provides per-session environment variables and identity tracking
for multi-platform message delivery. In harness_x (no gateway), sessions run
with a single identity and the process environment is used directly.

Called by: agent/agent_init.py, agent/conversation_compression.py,
agent/prompt_builder.py, agent/skill_commands.py, agent/skill_utils.py,
tools/approval.py, tools/terminal_tool.py, tools/environments/local.py
"""

import os
from typing import Any, Dict, Optional

# Sentinel used when a session var has been explicitly unset (vs never set).
_UNSET = object()

# Map of session-scoped variable names to their contextvars keys.
# Empty in the stub — no gateway sessions to track.
_VAR_MAP: Dict[str, Any] = {}


def get_session_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Return a session-scoped environment variable.

    Without the gateway, this falls back to the process environment.
    """
    return os.environ.get(key, default)


def set_current_session_id(session_id: str) -> None:
    """Set the current session identifier (no-op without gateway)."""
    pass
