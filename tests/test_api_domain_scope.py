# Copyright (c) 2026 Eric Cooper.
"""Domain-scoped Reviewers/Directors (#156): admin views & actions are confined
to the caller's allowed_domains, while Admin (level7) and Superuser (level8) are
unscoped — omnipotent across every domain.

End-to-end through the real middleware + capability deps, so it proves the scope
filters/guards are actually wired to the routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from rulebook.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "state_backend_kind", "local")
    monkeypatch.setattr(settings, "gcs_state_bucket", None)
    monkeypatch.setattr(
        settings,
        "invite_tokens_seed",
        {"tok_super": "boss", "tok_admin": "chief", "tok_dir": "deb", "tok_rev": "rae"},
    )
    monkeypatch.setattr(
        settings,
        "initial_roles",
        {"tok_super": "level8", "tok_admin": "level7", "tok_dir": "level6", "tok_rev": "level5"},
    )
    monkeypatch.setattr(settings, "default_allowed_domains", ["ultimate", "goaltimate"])
    # Reviewer + Director are scoped to ultimate only; Admin/Superuser ignore this.
    monkeypatch.setattr(
        settings,
        "initial_allowed_domains",
        {"tok_dir": ["ultimate"], "tok_rev": ["ultimate"]},
    )

    import api.main as main

    return TestClient(main.app)


def _as(client: TestClient, token: str) -> None:
    client.cookies.set("guest_session", token)


def _seed_reads(monkeypatch):
    """Two of everything: one ultimate row, one badminton row."""
    import api.main as main

    golds = [
        {"gold_id": "gu", "qa_id": "qu", "question": "?", "gold_answer": "a", "timestamp": "t", "author": "boss", "domains": ["ultimate"]},
        {"gold_id": "gb", "qa_id": "qb", "question": "?", "gold_answer": "b", "timestamp": "t", "author": "boss", "domains": ["badminton"]},
    ]
    feedback = [
        {"qa_id": "qu", "timestamp": "t", "rating": 5, "author": "boss"},
        {"qa_id": "qb", "timestamp": "t", "rating": 2, "author": "boss"},
    ]
    qa = [
        {"qa_id": "qu", "question": "u?", "answer": "A", "domains": ["ultimate"], "timestamp": "t2", "author": "boss"},
        {"qa_id": "qb", "question": "b?", "answer": "B", "domains": ["badminton"], "timestamp": "t1", "author": "boss"},
    ]
    monkeypatch.setattr(main, "read_latest_golds", lambda: golds)
    monkeypatch.setattr(main, "read_latest_curation", lambda: {})
    monkeypatch.setattr(main, "read_latest_feedback", lambda: feedback)
    monkeypatch.setattr(main, "read_qa_questions", lambda: {"qu": "u?", "qb": "b?"})
    monkeypatch.setattr(main, "read_qa_entries", lambda: qa)
    # Golds resolve to their persisted `domains` (skip index/known filtering).
    monkeypatch.setattr(main, "gold_target_domains", lambda g, *a, **k: g.get("domains", []))


def test_reviewer_reads_only_their_domains(client, monkeypatch):
    _seed_reads(monkeypatch)
    # Reviewer (level5) has *.view.all but is scoped to ultimate → sees only the
    # ultimate rows across all three tabs, never badminton.
    _as(client, "tok_rev")
    assert [g["qa_id"] for g in client.get("/advanced/golds").json()["golds"]] == ["qu"]
    assert [f["qa_id"] for f in client.get("/advanced/feedback").json()["feedback"]] == ["qu"]
    assert [q["qa_id"] for q in client.get("/advanced/questions").json()["questions"]] == ["qu"]


def test_admin_and_superuser_are_unscoped(client, monkeypatch):
    _seed_reads(monkeypatch)
    # Admin (level7) and Superuser (level8) are omnipotent across domains — the
    # allowlist is ignored, so both rows show.
    for tok in ("tok_admin", "tok_super"):
        _as(client, tok)
        assert {g["qa_id"] for g in client.get("/advanced/golds").json()["golds"]} == {"qu", "qb"}
        assert {f["qa_id"] for f in client.get("/advanced/feedback").json()["feedback"]} == {"qu", "qb"}
        assert {q["qa_id"] for q in client.get("/advanced/questions").json()["questions"]} == {"qu", "qb"}


def test_director_curation_guarded_by_domain(client, monkeypatch):
    import api.main as main

    _seed_reads(monkeypatch)
    monkeypatch.setattr(main, "log_gold_curation", lambda *a, **k: None)
    monkeypatch.setattr(main, "log_audit", lambda **k: None)

    # Director scoped to ultimate: curating the ultimate gold works…
    _as(client, "tok_dir")
    assert client.post("/advanced/gold-curation", json={"gold_id": "gu", "included": False}).status_code == 200
    # …but the badminton gold is out of scope → 403.
    assert client.post("/advanced/gold-curation", json={"gold_id": "gb", "included": False}).status_code == 403
    # Admin is unscoped → may curate the badminton gold.
    _as(client, "tok_admin")
    assert client.post("/advanced/gold-curation", json={"gold_id": "gb", "included": False}).status_code == 200


def test_director_clone_guarded_by_domain(client, monkeypatch):
    import api.main as main

    _seed_reads(monkeypatch)
    monkeypatch.setattr(main, "log_gold", lambda qa_id, **k: None)
    monkeypatch.setattr(main, "log_audit", lambda **k: None)

    _as(client, "tok_dir")
    assert client.post("/advanced/golds/gu/clone").status_code == 200
    assert client.post("/advanced/golds/gb/clone").status_code == 403


def test_rebuild_scoped_all_targets_only_caller_domains(client, monkeypatch):
    import api.main as main

    calls: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _Proc()

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    monkeypatch.setattr(main, "log_audit", lambda **k: None)
    monkeypatch.setattr(main, "available_domains", lambda: ["ultimate", "goaltimate", "badminton"])

    def _domains(cmds):
        return [c[c.index("--domain") + 1] for c in cmds if "--domain" in c]

    # Director scoped to ultimate.
    _as(client, "tok_dir")
    # Out-of-scope specific domain → 403, and no build runs.
    calls.clear()
    assert client.post("/advanced/rebuild-index", params={"domain": "badminton"}).status_code == 403
    assert calls == []
    # In-scope specific domain → builds just that one.
    calls.clear()
    assert client.post("/advanced/rebuild-index", params={"domain": "ultimate"}).status_code == 200
    assert _domains(calls) == ["ultimate"]
    # "Rebuild all" for a scoped caller → ONLY their in-scope domains, never badminton/all.
    calls.clear()
    assert client.post("/advanced/rebuild-index").status_code == 200
    assert _domains(calls) == ["ultimate"]

    # Admin is unscoped → "rebuild all" is one build over the whole corpus (no --domain).
    _as(client, "tok_admin")
    calls.clear()
    assert client.post("/advanced/rebuild-index").status_code == 200
    assert len(calls) == 1 and "--domain" not in calls[0]


def test_director_source_curation_guarded_by_domain(client, monkeypatch):
    import api.main as main

    monkeypatch.setattr(main, "log_source_curation", lambda *a, **k: None)
    monkeypatch.setattr(main, "log_audit", lambda **k: None)

    _as(client, "tok_dir")
    assert client.post("/advanced/source-curation", json={"path": "rules/ultimate/x.pdf", "included": False}).status_code == 200
    assert client.post("/advanced/source-curation", json={"path": "rules/badminton/y.pdf", "included": False}).status_code == 403
