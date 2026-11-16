# Copyright (c) 2026 Eric Cooper.
"""scripts/record_glance_answers.py runs its Claude calls through the real guardrails.

It once skipped app_state.initialize(), so the cost-cap hook had no counter and
the first call died with "'NoneType' object has no attribute 'enforce'". Here
the script runs end to end with the real hooks; only the Anthropic client and
retrieval are stubbed, and its state lands in a temp dir.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import record_glance_answers as record

import rulebook.generate as gen
import rulebook.pipeline as pipeline
from rulebook import app_state
from rulebook.config import settings
from rulebook.retrieve import RetrievedChunk


class _FakeAnthropic:
    def __init__(self, api_key):
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="Yes, forward or backward [checkers 4.2].")],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0),
            stop_reason="end_turn",
            model=kwargs["model"],
        )


def test_records_through_the_real_guardrails(monkeypatch, tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"answers": [{"question": "can a king move backwards?",
                                                "domain": "checkers", "answer": ""}]}))
    monkeypatch.setattr(record, "ANSWERS", answers)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "data_root", tmp_path)      # guardrail state goes here
    monkeypatch.setattr(settings, "state_backend_kind", "local")
    monkeypatch.setattr(app_state, "cost_counter", None)       # as in a fresh process
    monkeypatch.setattr(gen, "Anthropic", _FakeAnthropic)
    chunk = RetrievedChunk(text="4.2 How a king moves.", source="checkers.md", domain="checkers",
                           rule_id="4.2", page_start=1, page_end=1, distance=0.5)
    monkeypatch.setattr(pipeline, "retrieve", lambda question, domain, k: [chunk])

    record.main()

    saved = json.loads(answers.read_text())
    assert saved["answers"][0]["answer"] == "Yes, forward or backward [checkers 4.2]."
    assert (saved["answers"][0]["input_tokens"], saved["answers"][0]["output_tokens"]) == (100, 20)
    assert app_state.cost_counter is not None
