"""Behavior of the jsonl-log-backed interaction log (adopted in #4).

Exercises the semantics that matter to the admin digest + index builder:
last-row-wins per key, legacy string-rating skip, newest-first ordering,
and the on-disk row shape (rulebook flavour — `+00:00` timestamp, no id).
"""

import json

from rulebook import interaction_log as il


def test_gold_last_row_wins_and_newest_first(log_dir):
    il.log_gold("q1", gold_id="g1", question="Q1?", gold_answer="first")
    il.log_gold("q2", gold_id="g2", question="Q2?", gold_answer="q2ans")
    il.log_gold("q1", gold_id="g1", question="Q1?", gold_answer="second")  # supersedes g1

    golds = il.read_latest_golds()
    by_id = {g["gold_id"]: g for g in golds}
    assert by_id["g1"]["gold_answer"] == "second"
    assert by_id["g2"]["gold_answer"] == "q2ans"
    assert golds[0]["gold_id"] == "g1"  # most-recently-written first


def test_golds_owned_entities_and_legacy_fallback(log_dir):
    # Two distinct golds for the same qa_id (an author's and a clone's) coexist.
    il.log_gold("q1", gold_id="g1", question="Q1?", gold_answer="alice", author="alice")
    il.log_gold("q1", gold_id="g2", question="Q1?", gold_answer="bob", author="bob")
    # A legacy row (no gold_id) resolves to gold_id == qa_id — no migration.
    il.append_jsonl(
        log_dir / "gold.jsonl",
        {
            "v": 2,
            "qa_id": "qOld",
            "timestamp": il.utc_now_iso(timespec="auto", z=False),
            "question": "?",
            "gold_answer": "legacy",
            "author": "old",
        },
    )
    golds = il.read_latest_golds()
    assert {"g1", "g2", "qOld"} <= {g["gold_id"] for g in golds}
    assert sum(1 for g in golds if g["qa_id"] == "q1") == 2  # both survive


def test_feedback_skips_legacy_string_ratings(log_dir):
    # A legacy v1 row (rating is a string) written raw — must be excluded.
    il.append_jsonl(
        log_dir / "feedback.jsonl",
        {"v": 1, "qa_id": "qL", "timestamp": il.utc_now_iso(timespec="auto", z=False), "rating": "up"},
    )
    il.log_feedback("q1", rating=2, tags=["x"])
    il.log_feedback("q1", rating=5, tags=["helpful"])  # supersedes

    fb = il.read_latest_feedback()
    ids = {r["qa_id"] for r in fb}
    assert "qL" not in ids
    assert next(r for r in fb if r["qa_id"] == "q1")["rating"] == 5


def test_gold_curation_last_wins(log_dir):
    il.log_gold_curation("q1", included=True)
    il.log_gold_curation("q1", included=False)
    assert il.read_latest_curation() == {"q1": False}


def test_audit_appends_every_row(log_dir):
    il.log_audit(actor="alice", action="golds.curate", target="g1", detail={"included": False})
    il.log_audit(actor="bob", action="index.rebuild", detail={"ok": True})

    rows = il.read_audit()
    assert {r["action"] for r in rows} == {"golds.curate", "index.rebuild"}
    g = next(r for r in rows if r["action"] == "golds.curate")
    assert g["actor"] == "alice"
    assert g["target"] == "g1"
    assert g["detail"]["included"] is False
    assert len(il.read_audit(limit=1)) == 1  # cap honored


def test_source_curation_last_wins(log_dir):
    il.log_source_curation("rules/ultimate/x.md", included=True)
    il.log_source_curation("rules/ultimate/x.md", included=False)
    assert il.read_latest_source_curation() == {"rules/ultimate/x.md": False}


def test_qa_questions(log_dir):
    il.log_qa(
        "q9", question="What is a stall?", domain="ultimate", k=5,
        answer="A", chunks=[], input_tokens=1, output_tokens=1,
        model="m", stop_reason="end_turn",
    )
    assert il.read_qa_questions() == {"q9": "What is a stall?"}


def test_on_disk_shape_is_rulebook_flavour(log_dir):
    il.log_feedback("q1", rating=5, tags=["helpful"])
    row = json.loads((log_dir / "feedback.jsonl").read_text().splitlines()[-1])
    assert {"v", "qa_id", "timestamp", "rating", "tags", "comment"} <= set(row)
    assert row["timestamp"].endswith("+00:00")  # microsecond offset, no Z
    assert "id" not in row  # rulebook rows carry no minted ULID


def test_empty_reads_when_no_log(log_dir):
    assert il.read_latest_golds() == []
    assert il.read_latest_feedback() == []
    assert il.read_latest_curation() == {}
    assert il.read_qa_questions() == {}
    assert il.read_latest_source_curation() == {}
