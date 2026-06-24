# Contributing to Orrery

Thanks for your interest in improving Orrery! This guide explains how to propose changes.

## Ways to contribute

- **Report a bug** — open a [Bug report](../../issues/new?template=bug_report.md) issue.
- **Request a feature** — open a [Feature request](../../issues/new?template=feature_request.md) issue.
- **Submit a change** — open a pull request (see the workflow below).
- **Security issues** — please do **not** open a public issue; follow [`SECURITY.md`](SECURITY.md).

## Development setup

See the **Getting started** section of the [README](README.md) for prerequisites and how to run the
app locally (Python 3.12+, Node.js 20+, Docker Desktop).

## Pull request workflow

1. **Fork** the repository and create a branch from `main`:
   ```bash
   git checkout -b feature/short-description
   ```
2. **Make focused changes.** Keep each PR scoped to one logical change.
3. **Test before you push:**
   ```bash
   python -m pytest -q        # backend tests
   cd ui && npm run build     # the frontend must build cleanly
   ```
4. **Write a clear commit message** describing what changed and why.
5. **Open a pull request** against `main`. Fill in the PR template, link any related issue, and
   describe how you tested the change.
6. A maintainer will review. Please be responsive to feedback; small follow-up commits are fine.

## Coding guidelines

- **Python:** follow the style of the surrounding code; prefer clear names and small functions.
  Add or update tests under `tests/` for behavior changes.
- **Frontend:** match the existing React/JS patterns; keep components focused.
- **No secrets, ever.** Never commit credentials, tokens, `.env` files, or machine-specific paths.
  Secrets belong in the OS keychain at runtime, not in the repo.
- **Keep PRs reviewable** — avoid unrelated reformatting or sweeping renames.

## Reporting bugs well

A great bug report includes: what you expected, what happened, exact steps to reproduce, your OS and
versions, and any relevant (non-sensitive) logs or screenshots.

By contributing, you agree that your contributions are licensed under the project's
[Apache License 2.0](LICENSE).
