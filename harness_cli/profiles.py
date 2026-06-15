"""Minimal profile stub for harness_x.

harness_x is single-profile by design (the full 1.6k-line multi-profile
subsystem from hermes-agent was intentionally not ported). This module
provides the three names that the retained ``memory`` plugin imports from
``harness_cli.profiles`` so it loads and operates in single-profile mode.

If you later need true multi-profile isolation, port the full
``hermes_cli/profiles.py`` from hermes-agent (rewriting brand references).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from harness_constants import get_harness_home

_DEFAULT_PROFILE = "default"


def _get_default_hermes_home() -> Path:
    """Return the default (and only) harness home directory.

    Name kept for back-compat with code migrated from hermes-agent.
    """
    return get_harness_home()


def list_profiles() -> List[str]:
    """Return the list of profile names.

    harness_x has a single profile. Returns ``["default"]``.
    """
    return [_DEFAULT_PROFILE]


def get_active_profile_name() -> str:
    """Return the active profile name. Always ``"default"`` in harness_x."""
    return _DEFAULT_PROFILE
