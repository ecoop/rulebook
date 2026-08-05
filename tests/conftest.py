"""Shared fixtures + collection-time environment setup.

``rulebook.config`` instantiates ``Settings()`` at import and REQUIRES an
Anthropic key, so it must be present before any rulebook module is imported.
conftest.py is loaded before the test modules, so setting it here (module
level) covers every test. Tests never make real API calls — the dummy key
just satisfies the required-field validation.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy-key")

import pytest  # noqa: E402 — must follow the env default above

from rulebook import interaction_log  # noqa: E402


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Redirect interaction_log's JSONL files into a per-test tmp dir.

    ``_log_dir()`` is module-global and read at call time, so patching it
    here reroutes every log_*/read_* helper without touching real data/logs.
    """
    monkeypatch.setattr(interaction_log, "_log_dir", lambda: tmp_path)
    return tmp_path
