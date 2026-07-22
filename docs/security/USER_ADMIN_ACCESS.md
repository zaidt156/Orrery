# User / Admin Access

This document explains how Orrery handles solo use, team use, admin powers, member access, and
secret protection.

## Operating Modes

### Solo mode

Solo mode is the default when the `team_users` table has no users.

- The local user is treated as the admin.
- No team access key is required.
- Chats and projects are not filtered by owner.
- Provider keys and database URLs are managed locally through the OS keychain.
- This mode is intended for one person running Orrery on their own machine.

### Team mode

Team mode starts when the first admin is created from the Admin tab.

- Every person gets their own access key.
- Only a hash of each access key is stored in Postgres.
- The plaintext access key is shown once and then stored only on that user's machine through the OS
  keychain.
- Revoked or locked users are denied by the backend, not just hidden by the UI.
- Chats and projects are scoped by the current user's owner id.

## Roles

### Admin

Admins can:

- Create, revoke, restore, promote, demote, and delete team users.
- Configure provider API keys and official plan/CLI connections.
- Configure the primary Postgres database URL.
- Configure shared app settings such as branding, defaults, privacy mode, spending caps, and active
  models.
- Set workspace feature defaults.
- Set per-member feature access overrides.

Admins keep access to administration. Per-user feature overrides are meant for member accounts, so an
admin cannot accidentally lock all admins out through a member-level override.

### Member

Members can:

- Use their own chats, projects, files, and allowed Orrery features.
- Use models and provider connections that the admin has configured.
- See connected model status where it is safe to show masked state.

Members cannot:

- View raw API keys.
- View raw database connection strings.
- Save, clear, or test the primary database URL.
- Add/remove provider keys or official plan/CLI account connections.
- Add/remove custom model credentials.
- Change shared active model catalog state.
- Change shared workspace settings.

## Feature Access

Orrery now has two feature layers:

1. Workspace defaults stored in `feature_flags`.
2. Per-user overrides stored in `team_user_feature_flags`.

The effective permission is calculated in `backend/features/admin.py`.

- Solo mode uses workspace defaults.
- Team admins use workspace defaults.
- Team members use their override when present; otherwise they inherit the workspace default.
- Locked team clients receive no enabled feature flags.

The UI reads the effective feature value and hides unavailable tabs. The chat backend also uses the
effective feature value for capability gates such as code execution, file generation, web search, MCP,
deep research, and ontology context.

## Secret Handling

Secrets are not stored in project files or returned to the UI.

- Provider keys live in the OS keychain under `key:{provider}`.
- Custom model keys reuse the provider-key secret path under a custom namespace.
- The database URL is stored in the OS keychain when configured from Settings.
- `.env` is only a development/default configuration mechanism and must not ship with real secrets.
- API responses may return booleans or masked previews, never raw secret values.

For a team/server installation, the server/admin owns the real provider and database secrets. Members
connect with their own team access key and use the server-side configured capabilities without receiving
those secrets.

## Backend Enforcement

The backend is the security boundary. The UI is only a convenience layer.

Admin-only checks are applied to:

- Provider key mutation routes.
- Official plan/CLI connect, disconnect, install, login, and refresh routes.
- Database connection view, test, save, and clear routes.
- Shared model activation and custom model credential routes.
- Shared branding, defaults, privacy, and spending-cap settings.
- Team user management routes.

If a member calls these APIs directly, the backend returns `403 Admin access required`.

## Design Principles

The implementation follows a few SOLID-style boundaries:

- Single responsibility: `team.py` owns identity and roles; `admin.py` owns feature permissions;
  route modules only enforce access before calling feature services.
- Open/closed: new feature flags can be added to the `FEATURES` registry without changing the storage
  shape.
- Interface segregation: callers ask for `effective_flags()` or `_require_admin_access()` instead of
  duplicating role logic.
- Dependency inversion: UI components consume backend permission state instead of hard-coding team
  policy.
- Locked or revoked team clients fail closed, and so do database/configuration outages: an
  unverifiable team state reports team mode with a locked identity (never solo-admin), feature gates
  disable for team callers on read failures, and team bootstrap requires a successful query proving
  the team table is empty. Outage regression tests live in `tests/features/test_team_failclosed.py`.

## Current Follow-Ups

Unfinished access-control work is tracked only in the root [`TODO.md`](../../TODO.md). Product order
and security checkpoints are defined in [`PLAN.md`](../../PLAN.md); this document remains the durable
access contract rather than a second task list.
