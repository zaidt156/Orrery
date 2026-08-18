# Plan — bring the published site back in line with how Orrery actually works

**Status:** planned, not implemented. **Scope:** `docs/index.html` (landing page) and
`docs/guide.html` (user guide), both served by GitHub Pages from `main`.

## Why

The site describes a product that no longer exists in three places, and one of those breaks is mine:
renaming the README's `## Install And Run` to `## Install` left the landing page pointing at
`https://github.com/zaidt156/Orrery#install-and-run`, an anchor that no longer resolves.

The other two predate this session. The site leads with **Download** — a nav item, a hero button to
`/releases/latest`, and three cards offering "Windows releases" and "macOS previews" — but the
installers were deleted with the desktop shell, so the primary call to action points at packages
that are not published. Meanwhile the guide still teaches the eight-command setup (venv, `npm
install`, `npm run build`, `docker compose up`, `docker build`) that is now a single line, because
Orrery builds its own bundle and provisions PostgreSQL itself on first run.

Two smaller claims have also gone stale and are worth correcting while the files are open, because
both understate the project:

- the landing page lists "Automation APIs and editor wiring" as planned, but the Workflow API now
  exists — only canvas editing is missing;
- it says "Central Chat approvals, outage-safe authorization, redirect SSRF, and URL-secret
  handling remain P0 work", which DEVLOG Steps 151–152 closed. `TODO.md` no longer has a P0 section
  at all.

## Constraints

- Polish, not redesign: existing markup, classes, fonts and CSS stay as they are.
- Nothing may claim a capability that does not exist. Automations canvas editing and Media Hub are
  incomplete and must stay labelled as such.
- Every internal link must resolve after the change.

## Dependency order

`README.md` is the source the site links into, and it is already correct. So the site work has no
upstream dependency and the two files are independent of each other — but the landing page sets the
vocabulary ("Install", not "Download"), so it goes first and the guide follows it.

## Tasks

### 1. Landing page: replace Download with Install

Vertical slice — nav, hero, and section together, so the page is never half-renamed.

- Nav `Download` → `Install`, `href="#download"` → `href="#install"`; section `id` renamed to match.
- Hero primary button `Latest release` → `Install Orrery`, pointing at `#install` rather than
  `/releases/latest`.
- Replace the three release cards with the actual install: the one-line command, and a short note
  that the first run builds the workspace and starts PostgreSQL for you.
- Fix the dead anchor: `…/Orrery#install-and-run` → `…/Orrery#install`.

**Acceptance:** no link on the page resolves to `/releases`; `#install` exists and every in-page
`href="#…"` matches a real section id; the one-line command appears exactly as in the README.
**Verify:** extract every `href` and assert internal anchors have matching ids and no `/releases`
remains; diff the command string against the README.

### 2. Landing page: correct the two stale claims

- "In progress" card: Automations is *canvas editing*, not "Automation APIs and editor wiring".
- Security card: replace the "remain P0 work" sentence with what is now true, sourced from
  `TODO.md` rather than written from memory.

**Acceptance:** no sentence on the page contradicts `TODO.md` or `ARCHITECTURE.md`.
**Verify:** read both against the page; confirm `TODO.md` has no P0 section.

### 3. Guide: rewrite §02 "Installing it" around the one-line install

- Replace the eight-command block with `git clone … && cd Orrery && pip install -e . && orrery`.
- Say plainly what the first run does for you (builds the workspace bundle once, starts Docker and
  PostgreSQL, opens the browser) — this is the part that makes the single command believable.
- Keep the launch-code paragraph; it is still accurate.
- "Prefer not to use a terminal?" — keep it honest: portable packages can be built from the repo
  but none are published, so the command is the supported path.

**Acceptance:** the guide's install matches the README's; no step the app now performs itself is
still asked of the reader.
**Verify:** compare the guide's command to the README's character for character.

### 4. Guide: check the rest of the walkthrough against reality

Sections 03–12 were not part of this change but were written before it. Read them and correct only
what is now false (for example anything implying a separate window or a manual database step).

**Acceptance:** no remaining reference to installing a window, or to setup steps the app performs.
**Verify:** grep the guide for `window`, `install`, `docker`, `npm`.

## Checkpoint

After tasks 1–2, confirm the landing page renders and links resolve before touching the guide.
After 3–4, re-read both pages end to end as a new user would.

## Out of scope

Redesign, new sections, a published package on PyPI, and anything about the workspace-folder agent.
