# Security policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in the Legalize
pipeline engine, please report it responsibly.

**Do not open a public GitHub issue.**

Instead, email **security@legalize.dev** with:

- A description of the issue
- Steps to reproduce
- The affected component and version
- Any proof-of-concept code, if applicable

We aim to acknowledge reports within 3 business days and ship a fix
within 30 days for confirmed vulnerabilities.

## Scope

In scope:

- All fetcher code under `fetcher/{code}/` — country-specific clients, discovery, parsing
- The transformer and XML→Markdown processing
- The committer and git operations
- The CLI and orchestration logic (`pipeline.py`, `cli.py`)
- Configuration loading and state management

Out of scope:

- The content of the laws themselves in generated repositories
- Issues in third-party dependencies that have a pending upstream fix
- The Legalize API or web platform — report those separately at the web repo or the same email

## Signed commits

Maintainer commits are GPG-signed. Community PRs are not required to
sign, but the merge commit will be signed.
