# Copyright (c) 2026 Eric Cooper.
"""rulebook.notebook: settings pick up values loaded after import, and setup() reads no keys."""

import inspect

from rulebook import notebook
from rulebook.config import settings


def test_reload_settings_picks_up_new_environment(monkeypatch):
    # _reload_settings rewrites every field; put them all back afterwards.
    for name, value in settings.model_dump().items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setenv("RATE_LIMIT_RPM", "7")

    notebook._reload_settings()
    assert settings.rate_limit_rpm == 7


def test_setup_never_looks_for_keys_outside_dotenv():
    # A key the user stored elsewhere (e.g. Colab's Secrets panel) is read only in a
    # visible notebook cell, at the point of use, never quietly by setup().
    source = inspect.getsource(notebook)
    assert "userdata" not in source
    assert "google.colab" not in source


def test_build_index_prints_only_the_stage_lines(monkeypatch, capsys):
    log = (
        "[found ]  3 source files across 3 domain(s): checkers, poker, tennis\n"
        "[ingest]  checkers: reading checkers.md\n"
        "          -> 1 pages of text\n"
        "[chunk ]  checkers: 17 chunks (avg 281 chars)\n"
        "[embed ]  checkers: 17 chunks via local/minishlab/potion-retrieval-32M\n"
        "[store ]  checkers: wrote 17 rows\n"
        "[done  ]  built 1 domain(s), 17 total rows\n"
    )

    class Done:
        returncode, stdout, stderr = 0, log, ""

    monkeypatch.setattr(notebook.subprocess, "run", lambda *a, **k: Done())
    notebook.build_index("checkers")
    out = capsys.readouterr().out.splitlines()
    assert [line.split("]")[0] + "]" for line in out] == ["[ingest]", "[chunk ]", "[embed ]", "[store ]"]


def test_setup_builds_no_index():
    # Building happens in a visible notebook cell (build_index / ensure_index), not in setup().
    assert "index" not in inspect.getsource(notebook.setup).split('"""')[-1]
