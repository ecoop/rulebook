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

Container builds
    ``.dockerignore`` excludes ``.git/`` to keep the image small, so
    the runtime git lookup would produce "unknown". Pass ``RULEBOOK_GIT_SHA``
    and ``RULEBOOK_BUILD_NUM`` as build args / env vars — when set, they
    override the git lookup entirely. Same pattern pitchcraft uses; see
    Dockerfile ARG lines.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import settings


@dataclass(frozen=True)
class BuildInfo:
    sha: str          # short git SHA at process start, or "unknown"
    build_num: str    # monotonic commit count (git rev-list --count) or "?"
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
    # Env-var overrides win. Set by the Dockerfile via --build-arg so the
    # container reports its actual build commit even without .git/ shipped.
    env_sha = os.getenv("RULEBOOK_GIT_SHA")
    env_build_num = os.getenv("RULEBOOK_BUILD_NUM")

    if env_sha or env_build_num:
        sha = env_sha or "no-git"
        build_num = env_build_num or "?"
        dirty = False  # a stamped build implies a clean CI checkout
    else:
        sha = _git(["rev-parse", "--short", "HEAD"]) or "unknown"
        build_num = _git(["rev-list", "--count", "HEAD"]) or "?"
        # `git status --porcelain` counts both modified-tracked and untracked
        # files as dirty (ignored files are excluded). That's the "the working
        # tree differs from HEAD in a way I care about" definition we want.
        status = _git(["status", "--porcelain"])
        dirty = bool(status)

    return BuildInfo(
        sha=sha,
        build_num=build_num,
        dirty=dirty,
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# Captured once at import time. Every request reads the same values.
BUILD_INFO = _read_build_info()
