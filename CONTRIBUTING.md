# Contributing to Orrery

Thanks for your interest in improving Orrery! This guide explains how to propose changes.

## Ways to contribute

- **Report a bug** — open a [Bug report](../../issues/new?template=bug_report.md) issue.
- **Request a feature** — open a [Feature request](../../issues/new?template=feature_request.md) issue.
- **Submit a change** — open a pull request (see the workflow below).
- **Security issues** — please do **not** open a public issue; follow [`SECURITY.md`](SECURITY.md).

## Development setup

See the **Install** section of the [README](README.md) for prerequisites and the one-line install
(Python 3.12+, Node.js 20+, Docker Desktop; PostgreSQL with pgvector is provisioned for you).

### Hot reload

`orrery` serves the built bundle from `ui/dist`. For frontend work, point it at the Vite dev server
instead so changes reload without a rebuild:

```bash
# In .env:  ORRERY_DEV=1
cd ui && npm run dev        # terminal 1
orrery --no-browser         # terminal 2, then open the Vite URL
```

Set `ORRERY_DEV=0` and run `npm run build` to test the production path again. `python app.py` is
equivalent to `orrery`.

## Pull request workflow

1. **Fork** the repository and create a branch from `main`:
   ```bash
   git checkout -b feature/short-description
   ```
2. **Make focused changes.** Keep each PR scoped to one logical change.
3. **Test before you push:**
   ```bash
   python -m pytest -q             # backend tests
   python -m pytest -q -m "not db" # ...or skip the tests that need PostgreSQL
   cd ui && npm test               # frontend unit tests
   cd ui && npm run build          # the frontend must build cleanly
   ```
   Tests marked `db` need the local database (`docker compose up -d`). Without one they skip with
   a clear reason rather than stalling on a connection timeout. CI runs the full suite against a
   pgvector service on Linux and the `not db` subset on macOS and Windows.
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
