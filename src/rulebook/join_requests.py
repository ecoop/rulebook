# Copyright (c) 2026 Eric Cooper.
"""Join requests: people without an invite ask for one; the operator decides (#337).

A request is only a record. No account exists until it is approved, and
approval goes through the same user-creation path as the Users tab's add-user
(api/main.py), so there is one way to create a user.

Storage, in the state bucket:

    join_requests/<id>.json   one object per request. A purge is a real delete,
                              and two requests never contend for one object.
    join_settings.json        the live settings (switch, cap, approval defaults),
                              a whole-object snapshot like invite_tokens.json.

Every write carries the version (GCS generation) it read, so two people acting
on the same request can't both win: the second write fails with `Conflict`.

The public side (`GET /join/status`, `POST /join`) is part 2; it needs
guest-auth's public paths. `accepting()` and `new_request()` are its rules,
defined and tested here so part 2 is wiring only.
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Protocol

from jsonl_log import utc_now_iso

# ── Vocabulary ──────────────────────────────────────────────────────────────

MODE_CLOSED = "closed"
MODE_REFERRAL_ONLY = "referral-only"
MODE_OPEN = "open"
MODES: tuple[str, ...] = (MODE_CLOSED, MODE_REFERRAL_ONLY, MODE_OPEN)

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DECLINED = "declined"

SOURCE_WEB = "web"
SOURCE_IOS = "ios"
SOURCE_REFERRAL = "referral"
SOURCES: tuple[str, ...] = (SOURCE_WEB, SOURCE_IOS, SOURCE_REFERRAL)

NAME_MAX = 100
EMAIL_MAX = 254
HEARD_ABOUT_MAX = 500
CAP_MIN, CAP_MAX = 1, 100

# Deliberately loose: one @, something on each side, a dot in the domain. The
# operator reads every request, so this only catches typos and junk.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class JoinRequestError(ValueError):
    """A request or settings value failed validation (→ 422)."""


class NotFound(LookupError):
    """No request with that id (→ 404)."""


class NotPending(Exception):
    """The request was already decided (→ 409)."""


class Conflict(Exception):
    """Someone else wrote the object between our read and write (→ 409)."""


# ── Settings ────────────────────────────────────────────────────────────────


@dataclass
class JoinSettings:
    """The live join settings. Absent object = these defaults.

    Defaults are safe: requests start `closed`, so nothing opens until the
    operator switches it on.
    """

    mode: str = MODE_CLOSED
    pending_cap: int = 2
    default_role: str = "beginner"
    default_domains: list[str] = field(default_factory=lambda: ["goaltimate"])
    updated_at: str | None = None
    updated_by: str | None = None

    @classmethod
    def from_raw(cls, raw: dict | None) -> JoinSettings:
        """Parse a stored object, falling back field-by-field to the defaults."""
        base = cls()
        if not raw:
            return base
        mode = raw.get("mode", base.mode)
        cap = raw.get("pending_cap", base.pending_cap)
        domains = raw.get("default_domains", base.default_domains)
        return cls(
            mode=mode if mode in MODES else base.mode,
            pending_cap=cap if isinstance(cap, int) and CAP_MIN <= cap <= CAP_MAX else base.pending_cap,
            default_role=str(raw.get("default_role") or base.default_role),
            default_domains=[str(d) for d in domains] if isinstance(domains, list) else base.default_domains,
            updated_at=raw.get("updated_at"),
            updated_by=raw.get("updated_by"),
        )

    def to_raw(self) -> dict:
        return asdict(self)


def validate_settings(mode: str, pending_cap: int) -> None:
    """Shape checks the module owns. Role and domains are checked by the caller,
    which knows the role ladder and which domains exist."""
    if mode not in MODES:
        raise JoinRequestError(f"mode must be one of {list(MODES)}")
    if not CAP_MIN <= pending_cap <= CAP_MAX:
        raise JoinRequestError(f"pending_cap must be {CAP_MIN}–{CAP_MAX}")


def accepting(settings: JoinSettings, pending: int, source: str) -> bool:
    """Whether a new request from `source` would be accepted right now.

    closed: nothing. referral-only: referrals only. open: everything. The cap
    on waiting requests applies to public requests only; a referral already has
    someone vouching for it, and has its own per-referrer limit (later phase).
    """
    if settings.mode == MODE_CLOSED:
        return False
    if source == SOURCE_REFERRAL:
        return True
    if settings.mode == MODE_REFERRAL_ONLY:
        return False
    return pending < settings.pending_cap


# ── Records ─────────────────────────────────────────────────────────────────


def mint_request_id() -> str:
    """Long and random: in the iOS phase the id doubles as a claim code."""
    return "jr_" + secrets.token_urlsafe(24)


def _clean_line(value: str, what: str, max_len: int) -> str:
    v = " ".join(str(value).split())  # collapse whitespace, incl. newlines
    if not v:
        raise JoinRequestError(f"{what} is required")
    if len(v) > max_len:
        raise JoinRequestError(f"{what} must be at most {max_len} characters")
    if _CONTROL_RE.search(v):
        raise JoinRequestError(f"{what} contains control characters")
    return v


def new_request(
    *,
    name: str,
    email: str,
    heard_about: str,
    source: str = SOURCE_WEB,
    referred_by: str | None = None,
    now: str | None = None,
) -> dict:
    """Validate the fields and build a pending request record."""
    if source not in SOURCES:
        raise JoinRequestError(f"source must be one of {list(SOURCES)}")
    clean_email = _clean_line(email, "email", EMAIL_MAX)
    if not _EMAIL_RE.match(clean_email):
        raise JoinRequestError("email doesn't look like an email address")
    return {
        "v": 1,
        "id": mint_request_id(),
        "name": _clean_line(name, "name", NAME_MAX),
        "email": clean_email,
        "heard_about": _clean_line(heard_about, "heard_about", HEARD_ABOUT_MAX),
        "created_at": now or utc_now_iso(),
        "source": source,
        "referred_by": referred_by,
        "status": STATUS_PENDING,
        "decided_at": None,
        "decided_by": None,
        "invite_token": None,
        "granted_role": None,
        "granted_domains": None,
    }


# ── Storage ─────────────────────────────────────────────────────────────────


class JoinStore(Protocol):
    """Request objects with optimistic concurrency, plus the settings snapshot.

    `version` is what the store returned on read (or on the last `put`); 0 means
    "must not exist yet". A write or delete whose version is stale raises `Conflict`.
    """

    def list(self) -> list[tuple[dict, int]]: ...
    def get(self, request_id: str) -> tuple[dict, int] | None: ...
    def put(self, record: dict, *, version: int) -> int: ...
    def delete(self, request_id: str, *, version: int) -> None: ...
    def read_settings(self) -> dict | None: ...
    def write_settings(self, data: dict) -> None: ...


class GcsJoinStore:
    """JoinStore on the state bucket; versions are GCS object generations."""

    def __init__(self, bucket: str, prefix: str, settings_object: str) -> None:
        self._bucket_name = bucket
        self._prefix = prefix if prefix.endswith("/") else prefix + "/"
        self._settings_object = settings_object

    def _bucket(self):
        from google.cloud import storage

        return storage.Client().bucket(self._bucket_name)

    def _name(self, request_id: str) -> str:
        if not re.fullmatch(r"jr_[A-Za-z0-9_-]+", request_id):
            raise NotFound(request_id)  # never build a path from an odd id
        return f"{self._prefix}{request_id}.json"

    def list(self) -> list[tuple[dict, int]]:
        from google.cloud import storage

        out = []
        for blob in storage.Client().list_blobs(self._bucket_name, prefix=self._prefix):
            if not blob.name.endswith(".json"):
                continue
            # The version is the generation seen at listing time. If the object
            # changes before the download, the content is newer than the version
            # and any write based on it fails with Conflict, which is safe.
            out.append((json.loads(blob.download_as_text()), int(blob.generation)))
        return out

    def get(self, request_id: str) -> tuple[dict, int] | None:
        blob = self._bucket().get_blob(self._name(request_id))
        if blob is None:
            return None
        return json.loads(blob.download_as_text()), int(blob.generation)

    def put(self, record: dict, *, version: int) -> int:
        from google.api_core.exceptions import PreconditionFailed

        blob = self._bucket().blob(self._name(record["id"]))
        try:
            blob.upload_from_string(
                json.dumps(record, indent=2, sort_keys=True),
                content_type="application/json",
                if_generation_match=version,
            )
        except PreconditionFailed as exc:
            raise Conflict(record["id"]) from exc
        return int(blob.generation)

    def delete(self, request_id: str, *, version: int) -> None:
        from google.api_core.exceptions import NotFound as GcsNotFound
        from google.api_core.exceptions import PreconditionFailed

        try:
            self._bucket().blob(self._name(request_id)).delete(if_generation_match=version)
        except PreconditionFailed as exc:
            raise Conflict(request_id) from exc
        except GcsNotFound as exc:
            raise NotFound(request_id) from exc

    def read_settings(self) -> dict | None:
        blob = self._bucket().get_blob(self._settings_object)
        if blob is None:
            return None
        data = json.loads(blob.download_as_text())
        return data if isinstance(data, dict) else None

    def write_settings(self, data: dict) -> None:
        self._bucket().blob(self._settings_object).upload_from_string(
            json.dumps(data, indent=2, sort_keys=True), content_type="application/json"
        )


class MemoryJoinStore:
    """In-process JoinStore with the same version semantics, for tests and dev."""

    def __init__(self, records: Iterable[dict] = (), settings: dict | None = None) -> None:
        self._records: dict[str, tuple[dict, int]] = {}
        self._next = 1
        self._settings = settings
        for r in records:
            self.put(r, version=0)

    def list(self) -> list[tuple[dict, int]]:
        return [(dict(r), v) for r, v in self._records.values()]

    def get(self, request_id: str) -> tuple[dict, int] | None:
        hit = self._records.get(request_id)
        return (dict(hit[0]), hit[1]) if hit else None

    def put(self, record: dict, *, version: int) -> int:
        current = self._records.get(record["id"])
        if (current[1] if current else 0) != version:
            raise Conflict(record["id"])
        new_version = self._next
        self._records[record["id"]] = (dict(record), new_version)
        self._next += 1
        return new_version

    def delete(self, request_id: str, *, version: int) -> None:
        current = self._records.get(request_id)
        if current is None:
            raise NotFound(request_id)
        if current[1] != version:
            raise Conflict(request_id)
        del self._records[request_id]

    def read_settings(self) -> dict | None:
        return dict(self._settings) if self._settings is not None else None

    def write_settings(self, data: dict) -> None:
        self._settings = dict(data)


# ── Operations ──────────────────────────────────────────────────────────────


def list_requests(store: JoinStore) -> list[dict]:
    """All requests, pending first, then newest first within each status."""
    rows = [r for r, _ in store.list()]
    order = {STATUS_PENDING: 0, STATUS_APPROVED: 1, STATUS_DECLINED: 2}
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    rows.sort(key=lambda r: order.get(r.get("status"), 3))
    return rows


def count_pending(store: JoinStore) -> int:
    return sum(1 for r, _ in store.list() if r.get("status") == STATUS_PENDING)


def claim_pending(store: JoinStore, request_id: str) -> tuple[dict, int]:
    """Read a request that must still be pending; returns (record, version)."""
    hit = store.get(request_id)
    if hit is None:
        raise NotFound(request_id)
    record, version = hit
    if record.get("status") != STATUS_PENDING:
        raise NotPending(record.get("status"))
    return record, version


def decide(
    store: JoinStore,
    record: dict,
    version: int,
    *,
    status: str,
    decided_by: str | None,
    **extra: object,
) -> tuple[dict, int]:
    """Write a decision onto a claimed record; returns (record, new version).

    Raises Conflict if the record moved since it was claimed.
    """
    updated = {
        **record,
        **extra,
        "status": status,
        "decided_at": utc_now_iso(),
        "decided_by": decided_by,
    }
    return updated, store.put(updated, version=version)


def purge_declined(store: JoinStore) -> int:
    """Permanently delete every declined request. Returns how many went.

    A request that changed since the listing is skipped, not deleted.
    """
    purged = 0
    for record, version in store.list():
        if record.get("status") != STATUS_DECLINED:
            continue
        try:
            store.delete(record["id"], version=version)
        except (Conflict, NotFound):
            continue
        purged += 1
    return purged
