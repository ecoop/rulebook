# Copyright (c) 2026 Eric Cooper.
"""Join-request rules and storage semantics (#337), without the API."""

from __future__ import annotations

import pytest

from rulebook import join_requests as jr


def _req(**kw) -> dict:
    fields = {"name": "Pat Lee", "email": "pat@example.org", "heard_about": "Tuesday pickup"}
    fields.update(kw)
    return jr.new_request(**fields)


# ── new_request ─────────────────────────────────────────────────────────────


def test_new_request_builds_a_pending_record():
    r = _req(now="2026-11-23T00:00:00Z")
    assert r["status"] == jr.STATUS_PENDING
    assert r["source"] == "web"
    assert r["referred_by"] is None
    assert r["created_at"] == "2026-11-23T00:00:00Z"
    assert r["id"].startswith("jr_") and len(r["id"]) > 30  # long: doubles as a claim code later


def test_new_request_ids_are_unique():
    assert _req()["id"] != _req()["id"]


def test_new_request_collapses_whitespace_and_newlines():
    r = _req(name="  Pat \n Lee ", heard_about="from\r\nthe field")
    assert r["name"] == "Pat Lee"
    assert r["heard_about"] == "from the field"


@pytest.mark.parametrize(
    "kw",
    [
        {"name": "   "},
        {"name": "x" * (jr.NAME_MAX + 1)},
        {"email": "not-an-email"},
        {"email": "a@b"},
        {"heard_about": ""},
        {"heard_about": "x" * (jr.HEARD_ABOUT_MAX + 1)},
        {"source": "carrier-pigeon"},
        {"name": "Pat\x00"},
    ],
)
def test_new_request_rejects_bad_fields(kw):
    with pytest.raises(jr.JoinRequestError):
        _req(**kw)


# ── settings and accepting() ────────────────────────────────────────────────


def test_settings_default_to_closed_with_beginner_goaltimate():
    js = jr.JoinSettings.from_raw(None)
    assert js.mode == jr.MODE_CLOSED
    assert js.pending_cap == 2
    assert js.default_role == "beginner"
    assert js.default_domains == ["goaltimate"]


def test_settings_bad_stored_values_fall_back_field_by_field():
    js = jr.JoinSettings.from_raw({"mode": "wide-open", "pending_cap": 0, "default_role": "admin"})
    assert js.mode == jr.MODE_CLOSED
    assert js.pending_cap == 2
    assert js.default_role == "admin"  # kept: role validity is the API's check


def test_settings_round_trip():
    js = jr.JoinSettings(mode="open", pending_cap=5, default_role="annotator", default_domains=["ultimate"])
    assert jr.JoinSettings.from_raw(js.to_raw()) == js


@pytest.mark.parametrize("mode,cap", [("ajar", 2), ("open", 0), ("open", jr.CAP_MAX + 1)])
def test_validate_settings_rejects(mode, cap):
    with pytest.raises(jr.JoinRequestError):
        jr.validate_settings(mode, cap)


@pytest.mark.parametrize(
    "mode,pending,source,expected",
    [
        ("closed", 0, "web", False),
        ("closed", 0, "referral", False),
        ("referral-only", 0, "web", False),
        ("referral-only", 0, "ios", False),
        ("referral-only", 9, "referral", True),   # cap is for public requests only
        ("open", 0, "web", True),
        ("open", 1, "web", True),
        ("open", 2, "web", False),               # at the cap
        ("open", 2, "ios", False),
        ("open", 9, "referral", True),
    ],
)
def test_accepting(mode, pending, source, expected):
    js = jr.JoinSettings(mode=mode, pending_cap=2)
    assert jr.accepting(js, pending, source) is expected


# ── store + operations ──────────────────────────────────────────────────────


def test_store_create_conflicts_if_exists():
    r = _req()
    store = jr.MemoryJoinStore([r])
    with pytest.raises(jr.Conflict):
        store.put(r, version=0)


def test_decide_then_stale_version_conflicts():
    r = _req()
    store = jr.MemoryJoinStore([r])
    record, version = jr.claim_pending(store, r["id"])
    decided, new_version = jr.decide(store, record, version, status=jr.STATUS_DECLINED, decided_by="boss")
    assert decided["status"] == "declined" and decided["decided_by"] == "boss" and decided["decided_at"]
    assert new_version != version
    # A second decision made from the same (now stale) read loses.
    with pytest.raises(jr.Conflict):
        jr.decide(store, record, version, status=jr.STATUS_APPROVED, decided_by="chief")


def test_claim_pending_refuses_decided_and_missing():
    r = _req()
    store = jr.MemoryJoinStore([{**r, "status": "approved"}])
    with pytest.raises(jr.NotPending):
        jr.claim_pending(store, r["id"])
    with pytest.raises(jr.NotFound):
        jr.claim_pending(store, "jr_nope")


def test_list_requests_pending_first_then_newest():
    old_p = _req(now="2026-01-01T00:00:00Z")
    new_p = _req(now="2026-02-01T00:00:00Z")
    declined = {**_req(now="2026-03-01T00:00:00Z"), "status": "declined"}
    approved = {**_req(now="2026-04-01T00:00:00Z"), "status": "approved"}
    store = jr.MemoryJoinStore([old_p, declined, approved, new_p])
    assert [r["id"] for r in jr.list_requests(store)] == [new_p["id"], old_p["id"], approved["id"], declined["id"]]
    assert jr.count_pending(store) == 2


def test_purge_deletes_only_declined():
    keep_p = _req()
    keep_a = {**_req(), "status": "approved"}
    gone = [{**_req(), "status": "declined"} for _ in range(3)]
    store = jr.MemoryJoinStore([keep_p, keep_a, *gone])
    assert jr.purge_declined(store) == 3
    assert {r["id"] for r, _ in store.list()} == {keep_p["id"], keep_a["id"]}
    assert jr.purge_declined(store) == 0


def test_gcs_store_refuses_odd_ids():
    store = jr.GcsJoinStore("bucket", "join_requests", "join_settings.json")
    for bad in ("../invite_tokens", "jr_a/b", "x", "jr_a.json"):
        with pytest.raises(jr.NotFound):
            store._name(bad)
    assert store._name("jr_abc-_9") == "join_requests/jr_abc-_9.json"
