# Security Policy

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue, pull
request, or discussion for a suspected vulnerability.

Use GitHub's private vulnerability reporting:
[**Report a vulnerability**](https://github.com/ecoop/rulebook/security/advisories/new).
This opens a private advisory visible only to you and the maintainer.

Please include, as best you can:

- what the issue is and its impact (e.g. auth bypass, data exposure, injection);
- the steps or a proof of concept needed to reproduce it;
- the affected version, commit, or deployment (e.g. a hosted demo URL).

## What to expect

This is a small, maintained-as-time-allows project, so there is no guaranteed
response window — but reports are taken seriously and acknowledged as soon as
practical. Valid issues are fixed on `main`; please allow a reasonable chance to
ship a fix before any public disclosure. Only the latest `main` is supported.

## Scope

rulebook is an invite-gated application with authentication, capability-based
RBAC, and LLM cost governance. Reports touching those surfaces — the auth/invite
gate, role and domain scoping, or the cost-cap guard — are especially welcome.

Out of scope: findings against third-party services the app integrates with
(report those to the service), and issues that require a pre-compromised host or
account.
