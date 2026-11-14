# Copyright (c) 2026 Eric Cooper.
"""Ruleset editions: discovery, marker files, content hashes, `rulebook.add --edition`.

Every test builds its own rules tree under tmp_path; nothing touches the real
rules/ or data/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rulebook import add, registry, rulesets
from rulebook.config import settings
from rulebook.rulesets import MARKER_NAME, discover, ensure_markers, nest_flat


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _by_slug(root: Path) -> dict[str, Path]:
    return {r.slug: r.dir.relative_to(root) for r in discover(root).rulesets}


@pytest.fixture
def rules(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "rules"
    root.mkdir()
    monkeypatch.setattr(type(settings), "rules_dir", property(lambda self: root))
    return root


# ── Discovery ─────────────────────────────────────────────────────────────


def test_flat_rulesets_keep_their_folder_name_as_slug(rules):
    _write(rules / "tennis" / "tennis.md", "# Tennis")
    _write(rules / "goaltimate" / "a.md", "a")
    _write(rules / "goaltimate" / "b.txt", "b")
    d = discover(rules)
    assert _by_slug(rules) == {"goaltimate": Path("goaltimate"), "tennis": Path("tennis")}
    assert [p.name for p in d.by_slug()["goaltimate"].files] == ["a.md", "b.txt"]
    assert d.issues == []


def test_nested_editions_get_game_underscore_edition(rules):
    _write(rules / "ultimate" / "1990" / "Some Publisher Name v3 FINAL.pdf", "x")
    _write(rules / "ultimate" / "2026" / "official.md", "y")
    d = discover(rules)
    assert _by_slug(rules) == {
        "ultimate_1990": Path("ultimate/1990"),
        "ultimate_2026": Path("ultimate/2026"),
    }
    r = d.by_slug()["ultimate_1990"]
    assert (r.game, r.edition) == ("ultimate", "1990")
    assert d.issues == []


def test_edition_labels_normalize_into_the_slug(rules):
    _write(rules / "ultimate" / "WFDF 2025" / "r.md", "x")
    assert list(_by_slug(rules)) == ["ultimate_wfdf_2025"]


def test_mixed_folder_builds_own_files_and_reports_the_subfolder(rules):
    _write(rules / "ultimate" / "rules.md", "flat")
    _write(rules / "ultimate" / "1990" / "old.md", "old")
    _write(rules / "ultimate" / "images" / "logo.png", "not a rule file")
    d = discover(rules)
    assert _by_slug(rules) == {"ultimate": Path("ultimate")}
    [issue] = d.issues  # images/ holds no rule files, so only 1990/ is reported
    assert issue.level == "error"
    assert issue.path == rules / "ultimate" / "1990"
    assert "rulebook.rulesets nest ultimate" in issue.message


def test_too_deep_is_reported(rules):
    _write(rules / "ultimate" / "2026" / "r.md", "x")
    _write(rules / "ultimate" / "2026" / "appendix" / "a.md", "y")
    d = discover(rules)
    assert list(d.by_slug()) == ["ultimate_2026"]
    assert any(i.path == rules / "ultimate" / "2026" / "appendix" for i in d.issues)


def test_extracted_md_still_replaces_its_pdf(rules):
    _write(rules / "goaltimate" / "scan.pdf", "%PDF")
    _write(rules / "goaltimate" / "scan.extracted.md", "text")
    _write(rules / "goaltimate" / "other.pdf", "%PDF")
    files = discover(rules).by_slug()["goaltimate"].files
    assert sorted(p.name for p in files) == ["other.pdf", "scan.extracted.md"]


def test_dotfiles_and_folders_without_rule_files_are_ignored(rules):
    _write(rules / "tennis" / "t.md", "x")
    _write(rules / ".cache" / "x.md", "x")
    _write(rules / "empty" / "notes.json", "{}")
    assert list(_by_slug(rules)) == ["tennis"]


# ── Markers ───────────────────────────────────────────────────────────────


def test_first_build_writes_markers_from_the_path(rules):
    _write(rules / "tennis" / "t.md", "x")
    _write(rules / "ultimate" / "1990" / "r.md", "y")
    written = ensure_markers(discover(rules))
    assert sorted(p.relative_to(rules).as_posix() for p in written) == [
        f"tennis/{MARKER_NAME}", f"ultimate/1990/{MARKER_NAME}",
    ]
    flat = json.loads((rules / "tennis" / MARKER_NAME).read_text())
    nested = json.loads((rules / "ultimate" / "1990" / MARKER_NAME).read_text())
    assert flat["slug"] == "tennis" and "game" not in flat
    assert (nested["slug"], nested["game"], nested["edition"]) == ("ultimate_1990", "ultimate", "1990")
    # Second pass: nothing changed, nothing rewritten.
    assert ensure_markers(discover(rules)) == []


def test_marker_slug_wins_over_the_path(rules):
    _write(rules / "ultimate" / "2026" / "r.md", "x")
    rulesets.write_marker(rules / "ultimate" / "2026", "ultimate", "ultimate", "2026")
    assert _by_slug(rules) == {"ultimate": Path("ultimate/2026")}


def test_moved_folder_keeps_its_slug(rules):
    _write(rules / "ultimate" / "r.md", "x")
    ensure_markers(discover(rules))
    # Move the whole folder, dotfiles included, under a new game name + edition.
    (rules / "disc").mkdir()
    (rules / "ultimate").rename(rules / "disc" / "usau")
    d = discover(rules)
    assert _by_slug(rules) == {"ultimate": Path("disc/usau")}
    # The build refreshes where it is (game/edition), never the slug.
    ensure_markers(d)
    m = json.loads((rules / "disc" / "usau" / MARKER_NAME).read_text())
    assert (m["slug"], m["game"], m["edition"]) == ("ultimate", "disc", "usau")


def test_unreadable_marker_is_reported_not_overwritten(rules):
    _write(rules / "tennis" / "t.md", "x")
    _write(rules / "tennis" / MARKER_NAME, "{not json")
    d = discover(rules)
    assert d.rulesets == []
    assert d.issues[0].level == "error"
    assert ensure_markers(d) == []
    assert (rules / "tennis" / MARKER_NAME).read_text() == "{not json"


def test_two_folders_claiming_one_slug_are_both_refused(rules):
    _write(rules / "ultimate" / "1990" / "a.md", "a")
    _write(rules / "ultimate" / "2026" / "b.md", "b")
    for e in ("1990", "2026"):
        rulesets.write_marker(rules / "ultimate" / e, "ultimate")
    d = discover(rules)
    assert d.rulesets == []
    assert len([i for i in d.issues if "claimed by several" in i.message]) == 2


# ── Content hashes ────────────────────────────────────────────────────────


def test_identical_files_across_rulesets_warn(rules):
    _write(rules / "tennis" / "itf.md", "same bytes")
    _write(rules / "tennis_itf" / "copy.md", "same bytes")
    d = discover(rules, hash_files=True)
    assert {r.slug for r in d.rulesets} == {"tennis", "tennis_itf"}  # both still built
    [w] = d.issues
    assert w.level == "warning" and "identical content" in w.message
    assert "tennis_itf" in w.message


def test_folder_moved_without_marker_is_recognized_and_held_back(rules):
    doc = _write(rules / "ultimate" / "2026" / "r.md", "the 2026 rules")
    _write(rules / "ultimate" / "1990" / "r.md", "the 1990 rules")
    known = {"ultimate": {rulesets.file_sha256(doc)}}  # what the old flat build recorded
    d = discover(rules, known_hashes=known)
    # 2026/ matches the vanished "ultimate" slug: not built, no marker, a suggestion.
    assert {r.slug for r in d.rulesets} == {"ultimate_1990"}
    [issue] = [i for i in d.issues if i.path == rules / "ultimate" / "2026"]
    assert "'ultimate'" in issue.message and "rulebook.rulesets claim" in issue.message
    ensure_markers(d)
    assert not (rules / "ultimate" / "2026" / MARKER_NAME).exists()
    # Taking the suggestion restores the slug.
    assert rulesets.main(["claim", str(rules / "ultimate" / "2026"), "ultimate"]) == 0
    assert _by_slug(rules)["ultimate"] == Path("ultimate/2026")


def test_moved_detection_ignores_slugs_still_present(rules):
    a = _write(rules / "tennis" / "t.md", "same")
    _write(rules / "tennis_copy" / "t.md", "same")
    d = discover(rules, known_hashes={"tennis": {rulesets.file_sha256(a)}})
    assert {r.slug for r in d.rulesets} == {"tennis", "tennis_copy"}


def test_leftover_marker_on_a_game_folder_warns(rules):
    _write(rules / "ultimate" / "r.md", "x")
    ensure_markers(discover(rules))
    # A shell `mv ultimate/* ultimate/2026/` skips the dotfile marker.
    (rules / "ultimate" / "2026").mkdir()
    (rules / "ultimate" / "r.md").rename(rules / "ultimate" / "2026" / "r.md")
    d = discover(rules)
    assert any(i.path == rules / "ultimate" / MARKER_NAME for i in d.issues)


def test_folder_emptied_of_its_files_reports_its_marker(rules):
    # mv poker/* cards/ moves the files but not the dotfile marker.
    _write(rules / "poker" / "poker.md", "x")
    ensure_markers(discover(rules))
    (rules / "cards").mkdir()
    (rules / "poker" / "poker.md").rename(rules / "cards" / "poker.md")
    d = discover(rules)
    [issue] = [i for i in d.issues if i.path == rules / "poker" / MARKER_NAME]
    assert issue.level == "warning"
    assert "'poker'" in issue.message and "rulesets claim <their folder> poker" in issue.message


def test_edition_folder_emptied_of_its_files_reports_its_marker(rules):
    _write(rules / "tennis" / "2024" / "a.md", "a")
    _write(rules / "tennis" / "2026" / "b.md", "b")
    ensure_markers(discover(rules))
    (rules / "tennis" / "2024" / "a.md").unlink()
    d = discover(rules)
    assert [r.slug for r in d.rulesets] == ["tennis_2026"]
    assert [i.path for i in d.issues] == [rules / "tennis" / "2024" / MARKER_NAME]


def test_full_build_names_indexes_it_did_not_rebuild(tmp_path, capsys):
    import scripts.build_index as bi

    index = tmp_path / "index"
    for slug in ("checkers", "poker", "tennis_2026"):
        _write(index / slug / "manifest.json", json.dumps({"build_id": f"b-{slug}"}))
    assert bi.report_unbuilt_indexes(index, ["checkers"]) == ["poker", "tennis_2026"]
    out = capsys.readouterr().out
    assert "[keep  ]  poker: not built this time; its last index (build b-poker)" in out
    assert "checkers" not in out


# ── Nesting a flat game ───────────────────────────────────────────────────


def test_nest_flat_moves_everything_and_keeps_the_slug(rules):
    _write(rules / "ultimate" / "rules.pdf", "%PDF")
    _write(rules / "ultimate" / "notes.json", "{}")  # not a rule file: still moves, never deleted
    dest = nest_flat(rules, "ultimate", "2026")
    assert dest == rules / "ultimate" / "2026"
    assert sorted(p.name for p in dest.iterdir()) == [MARKER_NAME, "notes.json", "rules.pdf"]
    assert [p.name for p in (rules / "ultimate").iterdir()] == ["2026"]
    assert _by_slug(rules) == {"ultimate": Path("ultimate/2026")}


def test_nest_flat_leaves_existing_edition_folders(rules):
    _write(rules / "ultimate" / "rules.md", "new")
    _write(rules / "ultimate" / "1990" / "old.md", "old")
    nest_flat(rules, "ultimate", "2026")
    assert _by_slug(rules) == {"ultimate": Path("ultimate/2026"), "ultimate_1990": Path("ultimate/1990")}
    assert discover(rules).issues == []


# ── rulebook.add with an edition ──────────────────────────────────────────


@pytest.fixture
def add_root(rules, monkeypatch):
    monkeypatch.setattr(add, "_rules_root", lambda: rules)
    return rules


def _doc(tmp_path: Path, name: str, text: str) -> Path:
    return _write(tmp_path / "downloads" / name, text)


def test_add_flat_unchanged(add_root, tmp_path):
    assert add.main(["tennis", str(_doc(tmp_path, "ITF Rules 2026.md", "x")), "--no-build"]) == 0
    assert _by_slug(add_root) == {"tennis": Path("tennis")}


def test_add_first_edition_stays_flat_and_records_its_label(add_root, tmp_path):
    assert add.main(["ultimate", "2026", str(_doc(tmp_path, "u.md", "2026")), "--no-build"]) == 0
    assert _by_slug(add_root) == {"ultimate": Path("ultimate")}
    m = json.loads((add_root / "ultimate" / MARKER_NAME).read_text())
    assert (m["slug"], m["edition"]) == ("ultimate", "2026")


def test_add_second_edition_nests_the_first_and_keeps_its_slug(add_root, tmp_path):
    add.main(["ultimate", "--edition", "2026", str(_doc(tmp_path, "u.md", "2026")), "--no-build"])
    rc = add.main(["ultimate", "1990", str(_doc(tmp_path, "Old Rules.pdf", "1990")), "--no-build"])
    assert rc == 0
    assert _by_slug(add_root) == {
        "ultimate": Path("ultimate/2026"),
        "ultimate_1990": Path("ultimate/1990"),
    }
    assert (add_root / "ultimate" / "2026" / "u.md").read_text() == "2026"


def test_add_edition_to_unlabelled_flat_game_needs_a_label(add_root, tmp_path, monkeypatch, capsys):
    add.main(["ultimate", str(_doc(tmp_path, "u.md", "x")), "--no-build"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert add.main(["ultimate", "1990", str(_doc(tmp_path, "o.md", "y")), "--no-build"]) == 2
    assert "--existing-edition" in capsys.readouterr().err
    assert _by_slug(add_root) == {"ultimate": Path("ultimate")}  # nothing moved
    rc = add.main([
        "ultimate", "1990", str(_doc(tmp_path, "o.md", "y")),
        "--existing-edition", "2026", "--no-build",
    ])
    assert rc == 0
    assert _by_slug(add_root) == {"ultimate": Path("ultimate/2026"), "ultimate_1990": Path("ultimate/1990")}


def test_add_prompts_for_the_existing_label_on_a_tty(add_root, tmp_path, monkeypatch):
    add.main(["ultimate", str(_doc(tmp_path, "u.md", "x")), "--no-build"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "2026")
    assert add.main(["ultimate", "1990", str(_doc(tmp_path, "o.md", "y")), "--no-build"]) == 0
    assert _by_slug(add_root)["ultimate"] == Path("ultimate/2026")


def test_add_into_an_existing_edition_and_require_edition_once_nested(add_root, tmp_path, capsys):
    _write(add_root / "ultimate" / "1990" / "a.md", "a")
    _write(add_root / "ultimate" / "2026" / "b.md", "b")
    assert add.main(["ultimate", str(_doc(tmp_path, "c.md", "c")), "--no-build"]) == 2
    assert "has editions (1990, 2026)" in capsys.readouterr().err
    assert add.main(["ultimate", "1990", str(_doc(tmp_path, "c.md", "c")), "--no-build"]) == 0
    assert (add_root / "ultimate" / "1990" / "c.md").exists()


def test_add_refuses_an_edition_whose_slug_is_taken(add_root, tmp_path, capsys):
    _write(add_root / "ultimate_1990" / "x.md", "x")
    add.main(["ultimate", "2026", str(_doc(tmp_path, "u.md", "u")), "--no-build"])
    assert add.main(["ultimate", "1990", str(_doc(tmp_path, "o.md", "o")), "--no-build"]) == 2
    assert "already belongs to" in capsys.readouterr().err
    assert _by_slug(add_root)["ultimate"] == Path("ultimate")  # refused before moving anything


# ── Registry labels ───────────────────────────────────────────────────────


def test_edition_label_reads_game_and_edition(monkeypatch):
    monkeypatch.setattr(registry.settings, "state_backend_kind", "local")
    monkeypatch.setattr(registry.settings, "gcs_state_bucket", None)
    monkeypatch.setattr(
        registry.settings, "initial_domains", {"ultimate": {"display_name": "Ultimate (USAU)"}}
    )
    monkeypatch.setattr(registry, "_ruleset_meta", lambda: {
        "ultimate": ("ultimate", "2026"),
        "ultimate_1990": ("ultimate", "1990"),
        "beach_ultimate_2024": ("beach_ultimate", "2024"),
    })
    assert registry.display_labels(["ultimate", "ultimate_1990", "beach_ultimate_2024", "tennis"]) == {
        "ultimate": "Ultimate (USAU)",  # an explicit display_name still wins
        "ultimate_1990": "Ultimate (1990)",
        "beach_ultimate_2024": "Beach Ultimate (2024)",
        "tennis": "Tennis",
    }
    info = registry.domain_info("ultimate_1990")
    assert (info.game, info.edition) == ("ultimate", "1990")


def test_registry_reads_editions_from_the_rules_tree(rules, monkeypatch):
    monkeypatch.setattr(registry.settings, "state_backend_kind", "local")
    monkeypatch.setattr(registry.settings, "gcs_state_bucket", None)
    monkeypatch.setattr(registry.settings, "initial_domains", {})
    registry._meta_cache.clear()
    _write(rules / "ultimate" / "1990" / "r.md", "x")
    assert registry.display_labels(["ultimate_1990"]) == {"ultimate_1990": "Ultimate (1990)"}
    registry._meta_cache.clear()


# ── The builder ───────────────────────────────────────────────────────────


_RULE_TEXT = (
    "# Sample\n\n"
    "1.1 The disc. Play uses a round flying disc thrown between teammates across the field.\n\n"
    "1.2 The field. A rectangular field with an end zone at each end of the playing proper.\n"
)


class _FakeEmbedder:
    def embed(self, texts, *, input_type):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_build_records_hashes_and_editions_and_writes_markers(rules, tmp_path, monkeypatch, log_dir):
    import scripts.build_index as bi
    from rulebook.store import read_manifest

    doc = _write(rules / "ultimate" / "1990" / "Long Publisher Name.md", _RULE_TEXT)
    _write(rules / "tennis" / "t.md", _RULE_TEXT)
    monkeypatch.setattr(bi.settings, "index_path", tmp_path / "index")
    monkeypatch.setattr(bi.settings, "data_root", tmp_path / "data")
    monkeypatch.setattr(bi, "get_embedder", lambda: _FakeEmbedder())

    bi.main(["--domain", "ultimate_1990"])

    m = read_manifest(tmp_path / "index" / "ultimate_1990")
    assert (m["game"], m["edition"]) == ("ultimate", "1990")
    [src] = m["sources"]
    assert src["path"] == "ultimate/1990/Long Publisher Name.md"
    assert src["sha256"] == rulesets.file_sha256(doc)
    assert bi.known_source_hashes(tmp_path / "index") == {"ultimate_1990": {src["sha256"]}}
    # Discovery wrote every ruleset's marker, not just the one built.
    assert (rules / "tennis" / MARKER_NAME).exists()
    assert (rules / "ultimate" / "1990" / MARKER_NAME).exists()


def test_flat_sources_keep_their_domain(rules):
    import scripts.build_index as bi

    _write(rules / "checkers" / "checkers.md", "x")
    _write(rules / "ultimate" / "2026" / "r.md", "y")
    srcs = bi.discover_sources(rules, apply_curation=False)
    assert {(s.domain, s.path.name) for s in srcs} == {("checkers", "checkers.md"), ("ultimate_2026", "r.md")}


def test_committed_samples_have_markers_matching_their_folders():
    repo_rules = Path(__file__).resolve().parents[1] / "rules"
    for slug in ("checkers", "poker", "tennis"):
        assert rulesets.read_marker(repo_rules / slug)["slug"] == slug
    assert {r.slug for r in discover(repo_rules).rulesets} >= {"checkers", "poker", "tennis"}


# ── Elsewhere discovery is used ───────────────────────────────────────────


def test_eval_domain_chunks_finds_a_nested_slug(rules):
    from rulebook.eval import domain_chunks

    _write(rules / "ultimate" / "1990" / "r.md", _RULE_TEXT)
    chunks = domain_chunks("ultimate_1990")
    assert chunks and all(c.domain == "ultimate_1990" for c in chunks)
