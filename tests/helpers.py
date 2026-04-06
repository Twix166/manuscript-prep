from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run_cli(args: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [PYTHON, *args],
        cwd=str(cwd or REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

