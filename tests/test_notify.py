# Copyright (c) 2026 Eric Cooper.
"""New-request email (#337): message content, SMTP use, and never failing the caller."""

from __future__ import annotations

import pytest

from rulebook import notify
from rulebook.config import settings

RECORD = {
    "id": "jr_x",
    "name": "Pat Lee",
    "email": "pat@example.org",
    "heard_about": "Tuesday pickup",
    "source": "web",
    "referred_by": None,
}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.org")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_user", "sender@example.org")
    monkeypatch.setattr(settings, "smtp_password", "app-password")
    monkeypatch.setattr(settings, "notify_email", None)
    monkeypatch.setattr(settings, "public_url", "https://rules.example.org/")


class FakeSMTP:
    instances: list = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send", msg))


def test_email_content(configured):
    subject, body = notify.join_request_email(RECORD, pending=2)
    assert subject == "Rulebook join request: Pat Lee"
    assert "pat@example.org" in body
    assert "Tuesday pickup" in body
    assert "Requests waiting: 2" in body
    assert "https://rules.example.org/#/activity" in body
    assert "Referred by" not in body


def test_email_content_without_public_url(configured, monkeypatch):
    monkeypatch.setattr(settings, "public_url", None)
    _, body = notify.join_request_email({**RECORD, "referred_by": "chief"}, pending=1)
    assert "Users tab" not in body
    assert "Referred by: chief" in body


def test_notify_sends_over_starttls_to_smtp_user_by_default(configured, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    assert notify.notify_join_request(RECORD, pending=1) is True
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.org", 587)
    assert smtp.calls[0] == "starttls"
    assert smtp.calls[1] == ("login", "sender@example.org", "app-password")
    msg = smtp.calls[2][1]
    assert msg["To"] == "sender@example.org"
    assert msg["From"] == "sender@example.org"


def test_notify_email_overrides_recipient(configured, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "notify_email", "ops@example.org")
    notify.notify_join_request(RECORD, pending=1)
    assert FakeSMTP.instances[0].calls[2][1]["To"] == "ops@example.org"


def test_notify_skips_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    assert notify.notify_join_request(RECORD, pending=1) is False


def test_notify_swallows_smtp_failure(configured, monkeypatch):
    def boom(*a, **k):
        raise OSError("network unreachable")

    monkeypatch.setattr(notify.smtplib, "SMTP", boom)
    assert notify.notify_join_request(RECORD, pending=1) is False


def test_send_email_raises_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_user", None)
    with pytest.raises(RuntimeError):
        notify.send_email(to="x@example.org", subject="s", body="b")
