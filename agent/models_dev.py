"""Stub for agent.models_dev — model context length lookup table.

The full hermes-agent includes a comprehensive model database. This stub
provides a minimal fallback so that get_model_context_length() can proceed
without error. Returns None for all lookups, causing the caller to fall
through to its built-in heuristic defaults.
"""

from typing import Optional


def lookup_models_dev_context(provider: str, model: str) -> Optional[int]:
    """Look up known context length for a provider/model combination.

    Returns None to let the caller fall through to heuristic defaults.
    """
    return None
