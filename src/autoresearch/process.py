"""Small helpers for launching child processes consistently."""

from __future__ import annotations

import os
import subprocess
from types import ModuleType
from typing import Any


def windows_no_window_kwargs(
    *,
    creationflags: int = 0,
    os_name: str | None = None,
    subprocess_module: ModuleType | Any = subprocess,
) -> dict[str, Any]:
    """Return subprocess kwargs that avoid transient console windows on Windows."""

    current_os_name = os.name if os_name is None else os_name
    if current_os_name != "nt":
        return {}
    no_window = getattr(subprocess_module, "CREATE_NO_WINDOW", 0)
    return {"creationflags": creationflags | no_window}
