"""Build/version info shown in the UI footer.

Captured at server start so /meta can report which commit is serving
the answers and when the process was launched. Useful in bug reports:
"build 0257610*, started 2026-07-22 08:35 UTC" pins the exact code
that produced a bad answer.

Both the backend and the frontend live in this repo, so the backend's
git SHA is a fine "which version am I running" identifier for the
whole app — the frontend is served (or built) from the same working
tree. In dev, ``uvicorn --reload`` restarts the process on Python
changes, so the SHA and start time both update automatically. In
production, the info reflects deploy time — exactly what a bug report
needs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings


@dataclass(frozen=True)
class BuildInfo:
    sha: str          # short git SHA at process start, or "unknown"
    dirty: bool       # True if the working tree had uncommitted changes
    started_at: str   # ISO 8601 UTC, second precision


def _git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(settings.repo_root), *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def _read_build_info() -> BuildInfo:
    sha = _git(["rev-parse", "--short", "HEAD"]) or "unknown"
    # `git status --porcelain` counts both modified-tracked and untracked
    # files as dirty (ignored files are excluded). That's the "the working
    # tree differs from HEAD in a way I care about" definition we want.
    status = _git(["status", "--porcelain"])
    dirty = bool(status)
    return BuildInfo(
        sha=sha,
        dirty=dirty,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# Captured once at import time. Every request reads the same values.
BUILD_INFO = _read_build_info()
