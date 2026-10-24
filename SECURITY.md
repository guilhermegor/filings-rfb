# Security Policy

<!--
This file is written in ENGLISH on purpose, even when the project's published docs are
localized: a security policy is a security-researcher / contributor surface, like code, commit
messages and CI output. Only the published documentation follows the docs site's own language.
The language boundary is the AUDIENCE, not the repository.

GitHub auto-detects a root SECURITY.md and flips "Security policy" to Enabled — no API call.
The matching intake channel (private vulnerability reporting) is enabled by
`poe enable_security` / `bash bin/enable_security.sh`.
-->

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** A public issue discloses the
problem to everyone, including people who would exploit it, before a fix exists.

Instead, report it privately through GitHub:

1. Go to the **Security** tab of [filings-rfb](https://github.com/guilhermegor/filings-rfb).
2. Choose **Report a vulnerability** (GitHub private vulnerability reporting).
3. Describe the issue, the affected version(s), and — if you can — a minimal reproduction.

Private reporting keeps the discussion between you and the maintainers until a fix ships, and
gives you credit on the resulting advisory.

If private reporting is unavailable, contact the maintainer listed in `.github/CODEOWNERS`.

## What to expect

| Stage | What happens |
|-------|--------------|
| Acknowledgement | The report is confirmed as received. |
| Assessment | The maintainers reproduce it and judge severity and scope. |
| Fix | A patch is prepared privately, with a regression test where practical. |
| Disclosure | A GitHub Security Advisory is published and the fix is released. |

This is a volunteer-maintained project, so response times are best-effort rather than
contractual. Please allow a reasonable window before any public disclosure.

## Supported versions

Unless stated otherwise below, security fixes land on the **latest released version** only.
Consumers pinned to an older line should upgrade to pick up a fix.

| Version | Supported |
|---------|-----------|
| latest 1.x release | ✅   |
| < 1.0        | ❌        |

## Scope

In scope: vulnerabilities in this project's own code, its build/release workflows, or its
declared dependency set (a vulnerable transitive dependency this project pulls in).

Out of scope: vulnerabilities in third-party services this project merely talks to — report
those to the service's own security team. This includes the Receita Federal's public data share,
which is a third-party service this library only reads from.

## Automated security hygiene

This repository enables, via `poe enable_security`:

- **Private vulnerability reporting** — the intake channel described above.
- **Dependabot alerts** — notifications for known-vulnerable dependencies.
- **Dependabot security updates** — automatic PRs that fix an alerted vulnerability.

Ordinary (non-security) version bumps are handled separately by `.github/dependabot.yml`.
