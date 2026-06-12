"""Lightweight stub for gateway.status.

The full gateway provides process-status helpers for multi-process management.
In harness_x, we fall back to stdlib.

Called by: tools/process_registry.py
"""

import os


def _pid_exists(pid: int) -> bool:
    """Check whether a process with the given PID exists.

    Replaces the gateway's psutil-based implementation with a stdlib fallback.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True
    except OSError:
        return False
