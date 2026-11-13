# Copyright (c) 2026 Eric Cooper.
"""discover_sources: flat rulesets, edition folders, and the mixed-folder report.

Replaces #274's stopgap (skip every subfolder with a warning) now that editions
exist (docs/design/ruleset-editions.md): a game folder holding only edition
folders builds each one; a folder with its own files AND edition folders builds
its own files and reports the subfolders. More cases in tests/test_rulesets.py.
"""

from __future__ import annotations

from pathlib import Path

import scripts.build_index as bi


def _write(path: Path, text: str = "1.1 A rule.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_mixed_folder_builds_own_files_and_reports_the_subfolder(tmp_path, capsys) -> None:
    rules = tmp_path / "rules"
    _write(rules / "ultimate" / "rules.md")
    _write(rules / "ultimate" / "1990" / "Ultimate Rules 1990 (scan).pdf")

    sources = bi.discover_sources(rules, apply_curation=False, report=True)

    assert [(s.domain, s.path.name) for s in sources] == [("ultimate", "rules.md")]
    out = capsys.readouterr().out
    assert "[error ]" in out and str(rules / "ultimate" / "1990") in out
    assert "rulebook.rulesets nest ultimate" in out


def test_mixed_folder_report_is_quiet_unless_asked(tmp_path, capsys) -> None:
    # The API's read-only listings call discover_sources without report=True.
    rules = tmp_path / "rules"
    _write(rules / "ultimate" / "rules.md")
    _write(rules / "ultimate" / "1990" / "old.pdf")

    bi.discover_sources(rules, apply_curation=False)

    assert capsys.readouterr().out == ""


def test_game_folder_of_editions_builds_each_edition(tmp_path, capsys) -> None:
    rules = tmp_path / "rules"
    _write(rules / "ultimate" / "1990" / "Ultimate Rules 1990 (scan).pdf", "%PDF 1990")
    _write(rules / "ultimate" / "2026" / "official.md", "1.1 The 2026 rule.\n")

    sources = bi.discover_sources(rules, apply_curation=False, report=True)

    assert sorted((s.domain, s.path.name) for s in sources) == [
        ("ultimate_1990", "Ultimate Rules 1990 (scan).pdf"),
        ("ultimate_2026", "official.md"),
    ]
    assert capsys.readouterr().out == ""


def test_subfolder_without_rule_files_is_silent(tmp_path, capsys) -> None:
    rules = tmp_path / "rules"
    _write(rules / "tennis" / "tennis.md")
    _write(rules / "tennis" / "notes" / "scratch.json", "{}")

    sources = bi.discover_sources(rules, apply_curation=False, report=True)

    assert [s.path.name for s in sources] == ["tennis.md"]
    assert capsys.readouterr().out == ""
