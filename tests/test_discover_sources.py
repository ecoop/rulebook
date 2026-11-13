# Copyright (c) 2026 Eric Cooper.
"""discover_sources reads files directly in rules/<domain>/ and says when it skips a subfolder."""

from __future__ import annotations

from pathlib import Path

import scripts.build_index as bi


def _write(path: Path, text: str = "1.1 A rule.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_subfolder_with_rule_files_is_skipped_with_a_warning(tmp_path, capsys) -> None:
    rules = tmp_path / "rules"
    _write(rules / "ultimate" / "rules.md")
    _write(rules / "ultimate" / "1990" / "Ultimate Rules 1990 (scan).pdf")

    sources = bi.discover_sources(rules, apply_curation=False)

    assert [(s.domain, s.path.name) for s in sources] == [("ultimate", "rules.md")]
    out = capsys.readouterr().out
    assert "skipped rules/ultimate/1990/" in out
    assert "only files directly in rules/ultimate/" in out


def test_subfolder_without_rule_files_is_silent(tmp_path, capsys) -> None:
    rules = tmp_path / "rules"
    _write(rules / "tennis" / "tennis.md")
    _write(rules / "tennis" / "notes" / "scratch.json", "{}")

    sources = bi.discover_sources(rules, apply_curation=False)

    assert [s.path.name for s in sources] == ["tennis.md"]
    assert "skipped" not in capsys.readouterr().out
