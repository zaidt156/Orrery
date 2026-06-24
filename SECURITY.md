# Security Policy

Orrery is a local-first application: your model credentials and your data stay on your own machine.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue.

- Preferred: use GitHub's **private vulnerability reporting** (the repository's *Security → Report a
  vulnerability* tab), or
- Open a minimal private channel with the maintainer.

Include a clear description, reproduction steps, and impact. We aim to acknowledge reports promptly
and will coordinate a fix and disclosure timeline with you.

## How Orrery protects you

- **Credentials** are stored only in your operating system's keychain — never in files, logs, or the
  repository. The interface shows a masked preview only.
- **The local API** is bound to localhost and requires a per-session token.
- **Model-written code** (used for file generation) runs in an isolated, network-less sandbox with
  strict resource limits, never in the application process.
- **Database access** is read-only at the transaction layer and uses parameterized queries.

## Supported versions

Security fixes target the latest release on the default branch.
