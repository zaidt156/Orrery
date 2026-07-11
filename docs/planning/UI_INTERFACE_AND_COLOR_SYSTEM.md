# Orrery Interface and Color System

## Status

Approved for implementation on July 10, 2026.

## Objective

Orrery will expose two independent appearance choices:

1. **Interface** controls structure and interaction: `Classic` or `Concept`.
2. **Color theme** controls colors only: `Simple`, `Futuristic`, `Winter`, `Summer`, or `Observatory`.

The existing implementation couples palette, background scene, corner geometry, shadows, and page layout under one `data-theme` attribute. That is why choosing Futuristic also changes the shape and depth of the application. This work separates those responsibilities and completes the concept interface across every workspace instead of applying a shared banner to a few existing pages.

## Confirmed Product Intent

- Classic preserves the compact, pre-concept Orrery workflow and starts in Chat.
- Concept is a complete alternate interface based on the supplied concept screens and starts on Home.
- Switching interface must not change the selected color theme.
- Switching color theme must not change layout, geometry, density, or scroll behavior.
- The application shell stays locked to the window. The browser/body never becomes the page scroller.
- Only purposeful inner regions scroll: chat history, navigation lists, data tables, activity feeds, inspectors, and similarly bounded work areas.
- At desktop reference sizes, Home fits the available workspace without a page scrollbar. On small or unusually short windows, the active workspace may scroll internally so content remains reachable while the application chrome stays fixed.
- Concept screens use real Orrery data and actions. The reference artwork guides hierarchy and composition; fictional metrics or controls are not introduced just to match a picture.

## Terminology and State

### Interface mode

Stable values:

- `classic`
- `concept`

Stored as `orrery-interface` and applied to `<html data-interface="...">` before React renders.

### Color theme

Stable values:

- `simple`
- `futuristic`
- `winter`
- `summer`
- `observatory`

Stored as `orrery-color-theme` and applied to `<html data-color-theme="...">` before React renders.

The old `orrery-theme` value is migrated once to `orrery-color-theme`, preserving the user's current palette. Unknown stored values fall back safely to `classic` and `simple`.

### Ownership rule

Color themes may set only color-bearing tokens: backgrounds, surfaces, borders, text, accents, semantic colors, and translucent color variants.

Interface modes own all structural tokens and rules: spacing, type scale, radii, shadows, density, sidebar width, top bar presence, background patterns, elevation treatment, panel composition, and responsive behavior.

No selector shaped like `[data-color-theme="..."] .component` may alter layout or geometry.

## Application Shell Contract

### Shared invariants

- `html`, `body`, `#root`, `.app`, and `.app-body` fill the viewport and use `overflow: hidden`.
- Every flex/grid child that owns a scroll region has `min-width: 0` and `min-height: 0`.
- Focus order follows visual order.
- The update banner, lock screen, feature flags, team lock, database status, connection check, and lazy-loading behavior remain functional in both interfaces.
- Interface and color changes apply immediately, persist locally, and do not require a reload.

### Classic interface

- Compact icon rail based on the pre-concept `e03b636` shell.
- No Home navigation item; Chat is the default and fallback route.
- Existing view workflows and compact toolbars remain available.
- Custom branding remains supported without forcing the Concept top bar.
- The selected color theme recolors Classic without changing its compact geometry.

### Concept interface

- Labeled navigation rail with Orrery identity, feature-aware tabs, connection check, and license line.
- Fixed workspace/model top bar.
- Home is present and is the default route.
- Consistent panel hierarchy: workspace header, primary work surface, secondary navigation/inspector surfaces, and status/action areas.
- The supplied concept screens are the visual source for hierarchy, density, and placement.

## Scrolling Contract

| Surface | Scroll owner |
|---|---|
| App shell | Never scrolls |
| Classic views | Existing bounded view regions |
| Concept Home | No desktop page scroll; internal workspace fallback only below the fit threshold |
| Chat | Conversation list, transcript, and context inspector independently; composer remains pinned |
| Files/Projects | File list and preview/detail pane independently |
| Data | Source list/schema list and table/results region independently |
| Ontology | Collection/filter sidebar and detail inspector independently; graph canvas pans/zooms rather than page-scrolls |
| Dashboards | Dashboard list, widget canvas, and insight panel independently |
| Automations | Workflow list, canvas, node inspector, and run history independently |
| Agents | Agent list and activity feed independently |
| Settings/Admin/Skills/Models/Media | Their content panel scrolls inside the fixed shell when required |

Nested scroll regions use `overscroll-behavior: contain`, visible keyboard focus, and do not trap keyboard users.

## Concept Page Contracts

### Home

- Compact orbital workspace header, quick actions, real workspace metrics, recent activity, and privacy/system summary.
- Uses only real endpoint data already available to Home.
- Fits a normal desktop workspace without `.home-wrap` acting as a long document scroller.

### Chat

- Three-part workspace at wide sizes: conversation navigation, active thread, and context inspector.
- Thread is the only central vertical scroller; header and composer stay visible.
- Existing streaming, reasoning, attachments, version switching, projects, model controls, and context actions remain intact.
- Narrow layouts collapse secondary panes without removing access to them.

### Projects and Files

- Concept-style library/navigation pane plus focused editor/detail surface.
- Existing project, file, chat, upload, and deletion actions remain the source of truth.

### Data

- Workspace header plus real summary metrics derived from loaded connections, datasets, collections, and tables.
- Connected sources, imported workspaces, document collections, and read-only table browser become deliberate panels rather than one long vertical card stream.
- Connection forms, uploads, refresh, deletion, and read-only browsing retain current behavior.

### Ontology

- Three-pane knowledge workspace inspired by the ontology graph reference: collection/filter navigation, reusable-context canvas/list, and selected ontology details.
- Current create, edit, connect, upload, remove-file, search, and delete operations remain functional.
- No fabricated graph relationships are shown. If real relationships are unavailable, files become honest source nodes connected only to their selected ontology.

### Dashboards

- Dashboard navigation, widget canvas, and generation/insight controls follow the reference composition.
- Existing real dashboard specs, charts, revisions, refreshes, data imports, and SQL visibility remain intact.

### Automations

- Workflow list, builder canvas, node palette/inspector, run history, and templates use the concept hierarchy.
- Existing canvas behavior and controls remain; scroll is contained to the relevant pane.

### Agents

- Agent list, goal/scope/budget summary, controls, integrations, and live activity become a complete concept workspace.
- Existing demo/static behavior is not misrepresented as live backend data. Labels must remain honest until agent persistence exists.

### Media, Local Models, Skills, Admin, and Settings

- Each receives the same concept shell hierarchy and bounded content treatment, adapted to its real controls.
- Settings exposes separate Interface and Color theme groups with clear previews and `aria-pressed` state.
- The appearance controls themselves remain reachable in both interfaces and every color theme.

## Component and CSS Architecture

- `ui/src/lib/appearance.js`: stable values, normalization, migration, storage, DOM application, and change event.
- `ui/src/lib/appearance.test.js`: pure behavior tests for defaults, migration, and independent updates.
- A small React appearance provider/hook keeps App and Settings synchronized without a reload.
- Shared primitives remain presentational: workspace header, panel header, metric card, and bounded scroll region.
- Existing business/data logic stays in the current views and API client.
- Structural Concept rules are scoped under `[data-interface="concept"]`.
- Structural Classic rules are scoped under `[data-interface="classic"]`.
- Palette declarations are scoped only under `[data-color-theme="..."]`.
- Avoid duplicate Classic/Concept business logic. Conditional markup is allowed only where composition genuinely differs.

## Tech Stack and Commands

- React 18, plain JavaScript, Vite 6, existing Lucide icons, existing CSS.
- No new runtime dependency.

Commands:

- UI unit tests: `node --test ui/src/**/*.test.js`
- UI build: `npm run build` from `ui/`
- Backend regression tests: `python -m pytest`
- Python lint: `python -m ruff check backend app.py`
- Runtime: the local FastAPI app on its current loopback port, verified in an isolated in-app browser.

## Testing Strategy

- RED/GREEN unit tests for appearance normalization, legacy migration, persistence, and axis independence.
- Existing UI unit tests remain green.
- Vite production build after every UI slice.
- Real-browser checks in both interfaces and all five color themes.
- Desktop checks at 1440x900 and 1024x768; responsive checks at 768px and 320px widths.
- For each primary concept page: visual screenshot, clean console, keyboard access, accessible names, and scroll-owner inspection.
- Full Python regression suite because App/API integration must remain unchanged.

## Boundaries

### Always

- Preserve real data, existing actions, feature flags, local-only behavior, and accessibility.
- Use semantic tokens rather than raw palette colors in view components.
- Keep every commit buildable and testable.
- Preserve unrelated working-tree changes.

### Ask first

- Adding dependencies.
- Changing backend APIs or database schema.
- Removing an existing user-visible capability.

### Never

- Store appearance preferences on a server.
- Invent fake metrics or imply static examples are live.
- Let a color theme change layout.
- Reintroduce body/document scrolling.
- Read or expose browser credentials during runtime verification.

## Success Criteria

1. Interface and color selectors are visibly separate and independently persisted.
2. Every combination of two interfaces and five color themes renders without console errors.
3. Classic restores the compact icon-rail workflow and defaults to Chat without a Home tab.
4. Concept exposes Home and provides a deliberate concept composition for every enabled navigation destination.
5. Futuristic changes only colors; changing to or from it never moves or resizes UI.
6. At desktop sizes, the app chrome remains fixed and Home has no document-style scrollbar.
7. Chat keeps its header and composer fixed while its transcript scrolls.
8. Data, Ontology, Dashboards, Automations, and Agents have bounded, page-specific layouts matching the reference hierarchy.
9. Appearance selection has no flash of the wrong choice on startup.
10. Existing UI tests, production build, Python tests, and runtime browser checks pass.
