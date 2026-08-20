# Copyright (c) 2026 Eric Cooper.
"""Per-domain index layout (#128): one store per domain under the index root."""

from __future__ import annotations

from rulebook.chunking import Chunk
from rulebook.store import (
    domain_index_path,
    list_domains,
    open_domain_store,
    read_manifest,
    write_store,
)


def _chunk(domain: str, rule_id: str, text: str) -> Chunk:
    return Chunk(source="s.pdf", domain=domain, rule_id=rule_id,
                 page_start=1, page_end=1, text=text)


def _write(root, domain, chunk, vec):
    write_store(
        domain_index_path(root, domain),
        [chunk],
        [vec],
        provider="p",
        model="m",
        manifest_extra={"domain": domain, "chunks_by_domain": {domain: 1}},
    )


def test_each_domain_is_its_own_store(tmp_path):
    root = tmp_path / "index"
    _write(root, "ultimate", _chunk("ultimate", "1", "the stall count is ten"), [1.0, 0.0])
    _write(root, "badminton", _chunk("badminton", "7", "best of three games"), [0.0, 1.0])

    # list_domains returns the built domain subdirs, sorted.
    assert list_domains(root) == ["badminton", "ultimate"]

    # A domain store holds ONLY its own rows — no masking needed.
    rows = open_domain_store(root, "ultimate").search([1.0, 0.0], k=5)
    assert len(rows) == 1
    assert rows[0]["domain"] == "ultimate"
    assert read_manifest(domain_index_path(root, "ultimate"))["count"] == 1


def test_list_domains_ignores_dirs_without_a_manifest(tmp_path):
    root = tmp_path / "index"
    root.mkdir()
    (root / "notadomain").mkdir()  # a stray dir with no manifest
    _write(root, "curling", _chunk("curling", "R6", "free guard zone"), [1.0, 0.0])
    assert list_domains(root) == ["curling"]


def test_list_domains_empty_when_no_index(tmp_path):
    assert list_domains(tmp_path / "missing") == []
