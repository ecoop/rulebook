# Copyright (c) 2026 Eric Cooper.
"""Which domains a gold applies to (#135).

A heading-less gold used to fan into EVERY domain's index; most are actually
domain-specific. This resolves the domains a gold NAMES — never today's live
"all" (which grows over time) — from, in order:

    explicit  the gold row's persisted ``domains`` (stamped at authoring time)
    qa        the frozen domain list from the gold's originating qa_log row
    legacy    a configured fallback for ambiguous pre-v4 "all" golds

The result is always intersected with the currently-known domains, so a gold
attributed to a removed domain drops out rather than erroring.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

# A gold answer may be split into per-domain sections by ``## <Domain>`` headings.
DOMAIN_HEADING = re.compile(r"^\s*##\s+([A-Za-z][A-Za-z_ -]*?)\s*$", re.M)


def heading_domains(text: str, known: Iterable[str]) -> list[str]:
    """The known domains named by ``## <Domain>`` headings in a gold's text."""
    known_set = set(known)
    return sorted(
        {m.group(1).strip().lower() for m in DOMAIN_HEADING.finditer(text)} & known_set
    )


def qa_domains(qa_row: Mapping[str, object]) -> list[str] | None:
    """The domains a gold's originating question ran against, frozen in its
    qa_log row — or ``None`` for an ambiguous pre-v4 "all" (``domain`` null and
    no ``domains`` list), which the caller resolves to the legacy set."""
    doms = qa_row.get("domains")
    if doms:
        return [str(d) for d in doms]  # v4+ froze the resolved list
    single = qa_row.get("domain")
    return [str(single)] if single else None  # None = old cross/"all"


def resolve_domains(
    *,
    explicit: Iterable[str] | None,
    qa: Iterable[str] | None,
    legacy: Iterable[str],
    known: Iterable[str],
) -> list[str]:
    """Domains a heading-less gold should index into: explicit ▸ qa ▸ legacy,
    intersected with ``known``. Falls back to legacy∩known if the chosen set has
    nothing that still exists. Never expands to all of ``known`` implicitly."""
    known_set = set(known)
    chosen = list(explicit or []) or list(qa or []) or list(legacy)
    result = [d for d in chosen if d in known_set]
    if result:
        return result
    return [d for d in legacy if d in known_set]


def gold_target_domains(
    gold_row: Mapping[str, object],
    qa_index: Mapping[str, Mapping[str, object]],
    *,
    legacy: Iterable[str],
    known: Iterable[str],
) -> list[str]:
    """Every domain a gold applies to — for stamping/migration (#135).

    ``## <Domain>`` sections win; else the persisted ``domains``; else the
    originating qa_log row's frozen list; else the legacy set. Always ⊆ known.
    """
    heads = heading_domains(str(gold_row.get("gold_answer", "")), known)
    if heads:
        return heads
    qrow = qa_index.get(str(gold_row.get("qa_id", "")))
    return resolve_domains(
        explicit=gold_row.get("domains"),  # type: ignore[arg-type]
        qa=qa_domains(qrow) if qrow else None,
        legacy=legacy,
        known=known,
    )
