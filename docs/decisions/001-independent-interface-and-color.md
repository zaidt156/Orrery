# ADR-001: Separate interface modes from color themes

## Status

Accepted

## Date

2026-07-10

## Context

Orrery's original theme attribute controlled colors, page geometry, shadows, background scenes, and
navigation treatment together. Users could not keep a preferred layout while changing colors, and
the concept references were applied as a global reskin rather than a complete alternate interface.

## Decision

Use two independent persisted axes: `classic|concept` for interface structure and
`simple|futuristic|winter|summer|observatory` for color. Palette selectors may set color tokens only.
Classic preserves the pre-concept compact workflow; Concept implements the reference-driven shell
and page compositions.

## Alternatives Considered

### Keep one combined theme selector

Rejected because every new palette multiplies layout variants and changing color unexpectedly moves
the interface.

### Duplicate the entire React application per design

Rejected because business logic and behavior would diverge. The two modes share data/actions and
branch only where composition genuinely differs.

## Consequences

- Appearance state needs migration from the old `orrery-theme` key.
- Structural CSS must be scoped to interface mode.
- Browser verification covers all ten interface/color combinations.
