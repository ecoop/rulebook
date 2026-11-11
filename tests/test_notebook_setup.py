# Copyright (c) 2026 Eric Cooper.
"""rulebook.notebook: the key comes from Colab's Secrets panel when it's there."""

import sys
import types

from rulebook import notebook
from rulebook.config import settings


def _fake_colab(monkeypatch, secret):
    userdata = types.ModuleType("google.colab.userdata")
    userdata.get = lambda name: secret if name == "ANTHROPIC_API_KEY" else None
    colab = types.ModuleType("google.colab")
    colab.userdata = userdata
    monkeypatch.setitem(sys.modules, "google.colab", colab)
    monkeypatch.setitem(sys.modules, "google.colab.userdata", userdata)


def test_colab_secret_becomes_the_key(monkeypatch):
    # _reload_settings rewrites every field; put them all back afterwards.
    for name, value in settings.model_dump().items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    _fake_colab(monkeypatch, "sk-from-colab")

    assert notebook._key_from_colab_secrets() is True
    notebook._reload_settings()
    assert settings.anthropic_api_key == "sk-from-colab"


def test_no_colab_or_no_secret_changes_nothing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delitem(sys.modules, "google.colab", raising=False)
    assert notebook._key_from_colab_secrets() is False

    _fake_colab(monkeypatch, None)
    assert notebook._key_from_colab_secrets() is False


def test_an_existing_key_wins_over_the_colab_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-already-set")
    _fake_colab(monkeypatch, "sk-from-colab")
    assert notebook._key_from_colab_secrets() is False
