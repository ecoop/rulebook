# Copyright (c) 2026 Eric Cooper.
"""rulebook.notebook: settings pick up values loaded after import, and setup() reads no keys."""

import inspect

from rulebook import notebook
from rulebook.config import settings


def test_reload_settings_picks_up_new_environment(monkeypatch):
    # _reload_settings rewrites every field; put them all back afterwards.
    for name, value in settings.model_dump().items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setenv("RATE_LIMIT_RPM", "7")

    notebook._reload_settings()
    assert settings.rate_limit_rpm == 7


def test_setup_never_looks_for_keys_outside_dotenv():
    # A key the user stored elsewhere (e.g. Colab's Secrets panel) is read only in a
    # visible notebook cell, at the point of use, never quietly by setup().
    source = inspect.getsource(notebook)
    assert "userdata" not in source
    assert "google.colab" not in source
