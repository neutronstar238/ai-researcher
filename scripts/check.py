"""Run the local quality gates that mirror CI."""

from __future__ import annotations

import subprocess
import sys


COMMANDS = [
    ["poetry", "run", "ruff", "check", "src", "tests"],
    ["poetry", "run", "mypy", "src"],
    ["poetry", "run", "pytest", "tests/smoke", "tests/unit"],
]


def main() -> int:
    for command in COMMANDS:
        print(f"\n$ {' '.join(command)}", flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
