# Documentation

Use this page as the documentation index. Project status is intentionally kept in four canonical
documents so plans, completed work, and implemented architecture cannot drift into one another.

| Document or folder | Contents |
|---|---|
| [`../ARCHITECTURE.md`](../ARCHITECTURE.md) | The complete architecture as implemented |
| [`../PLAN.md`](../PLAN.md) | Product direction, sequencing, decisions, and checkpoints |
| [`../TODO.md`](../TODO.md) | Current unfinished tasks only |
| [`history/DEVLOG.md`](history/DEVLOG.md) | Append-only completed-work history |
| [`security/USER_ADMIN_ACCESS.md`](security/USER_ADMIN_ACCESS.md) | Durable solo/team access and secret-handling contract |
| `generated/` | Generated local documentation packages; ignored by Git |

Start with [`security/USER_ADMIN_ACCESS.md`](security/USER_ADMIN_ACCESS.md) for the current solo/team
role model, per-user feature permissions, and secret-handling rules.

Architecture and roadmap details live only in the root canonical documents above. Durable design
rationale remains in [`decisions/`](decisions/); security contracts remain in [`security/`](security/).
