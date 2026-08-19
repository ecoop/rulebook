# Copyright (c) 2026 Eric Cooper.
"""Tests for the domain registry (#113 part 2): defaults, enabled, labels."""

from __future__ import annotations

import pytest

import rulebook.registry as registry


@pytest.fixture(autouse=True)
def _clear_cache():
    registry._registry_cache.clear()
    yield
    registry._registry_cache.clear()


@pytest.fixture
def local_seed(monkeypatch):
    # Local backend: the registry resolves from the env seed only (no GCS).
    monkeypatch.setattr(registry.settings, "state_backend_kind", "local")
    monkeypatch.setattr(registry.settings, "gcs_state_bucket", None)
    monkeypatch.setattr(registry.settings, "initial_domains", {})


def test_undeclared_domain_defaults_to_enabled_titlecased(local_seed):
    info = registry.domain_info("goaltimate")
    assert info.enabled is True
    assert info.display_name == "Goaltimate"
    assert info.sources == []
    assert info.numbering is None


def test_multiword_slug_default_name(local_seed):
    assert registry.domain_info("beach_ultimate").display_name == "Beach Ultimate"


def test_declared_entry_overrides_defaults(local_seed, monkeypatch):
    monkeypatch.setattr(
        registry.settings,
        "initial_domains",
        {
            "ultimate": {
                "display_name": "Ultimate (USAU)",
                "sources": ["https://usaultimate.org/rules"],
                "numbering": "[{rule_id}]",
                "enabled": True,
            },
            "badminton": {"enabled": False},
        },
    )
    u = registry.domain_info("ultimate")
    assert u.display_name == "Ultimate (USAU)"
    assert u.sources == ["https://usaultimate.org/rules"]
    assert u.numbering == "[{rule_id}]"
    # A disabled domain keeps its (default) name but is filtered by visibility.
    assert registry.domain_info("badminton").enabled is False


def test_visible_domains_filters_disabled(local_seed, monkeypatch):
    monkeypatch.setattr(
        registry.settings, "initial_domains", {"badminton": {"enabled": False}}
    )
    # Order preserved; the disabled one drops out; undeclared ones stay (default on).
    assert registry.visible_domains(["ultimate", "badminton", "goaltimate"]) == [
        "ultimate",
        "goaltimate",
    ]


def test_display_labels(local_seed, monkeypatch):
    monkeypatch.setattr(
        registry.settings, "initial_domains", {"ultimate": {"display_name": "Ultimate (USAU)"}}
    )
    assert registry.display_labels(["ultimate", "goaltimate"]) == {
        "ultimate": "Ultimate (USAU)",
        "goaltimate": "Goaltimate",
    }
