"""Small helpers for launching child processes consistently."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def windows_no_window_kwargs(*, creationflags: int = 0) -> dict[str, Any]:
    """Return subprocess kwargs that avoid transient console windows on Windows."""

    if os.name != "nt":
        return {}
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": creationflags | no_window}
