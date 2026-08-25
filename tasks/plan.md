# Plan — Office previews without LibreOffice

**Status:** planned, not implemented. **Scope:** `backend/features/filepreview.py`,
`backend/features/sandbox.py`, a new `backend/features/office_render.py`,
`backend/api/routes_files.py`, and the Settings preview panel.

## Why

Three separate problems share one cause, and none of them is really about LibreOffice.

**The parse runs in this process.** When LibreOffice is absent — the default on a fresh machine —
DOCX/XLSX/PPTX previews are produced by python-docx, openpyxl and python-pptx running inside the
backend, with the keychain, the database connection and the user's files in reach. That is the last
in-process parse of untrusted documents, and PLAN.md Workstream 2's checkpoint fails on it.

**ODF does not work at all.** TODO.md says ODT/ODS/ODP are covered by "the optional LibreOffice
converter". They are not: `to_preview` gates the converter on `ext in ("pptx","docx","xlsx","xlsm")`,
so an `.odt` never reaches it and falls through to "Preview unavailable for this file type" whether
LibreOffice is installed or not.

**The product implies LibreOffice is required.** `office_preview_status()` reports
`available: false` without it, and Settings offers to install it. A user reads that as "previews are
broken until you install a 500 MB office suite", when in fact previews work — just through a
different renderer.

The sandbox image already carries `python-docx`, `openpyxl`, `python-pptx`, `odfpy`, `lxml` and
`Pillow`. Everything needed is present; nothing new has to be installed anywhere.

## Architecture decisions

**Move the existing renderers, do not rewrite them.** The alternative — parsing in the container and
emitting a structured JSON document model for the host to render — is cleaner on paper and much
riskier here: it means rewriting all three renderers with no visual regression tests to catch a
slip. Running the *same code* in a different place changes the privileges without changing a byte of
output.

**The byte-identical guard.** Because it is the same code, a test can render a fixture through the
host path and the container path and assert the HTML is byte-for-byte identical. That is a stronger
regression guard than any screenshot comparison, and it is what makes this refactor safe to do in
one pass. If the outputs ever diverge, the test says so immediately.

**Generated HTML is already untrusted output.** Building preview HTML inside the container does not
weaken anything: the result is served from `/artifacts/` under a CSP into a sandboxed iframe, which
is exactly how it is treated today.

**A sandbox failure means no preview.** Same rule as the PDF renderer (Step 183). Falling back to a
host parse precisely when the container broke would make the boundary optional for the documents
most likely to break a parser.

**LibreOffice stays, demoted.** It is not removed — where it happens to be installed it still gives
page-faithful output, and ripping it out would be a regression for those users. What changes is that
its absence stops being reported as a fault. It becomes an optional enhancement, not a prerequisite.

## Dependency graph

```
sandbox image  (python-docx, openpyxl, python-pptx, odfpy, lxml, Pillow — all present)
      │
      └── office_render.py         pure renderers, no host-only imports        [Task 1]
              │
              ├── sandbox.render_office_html()  +  to_preview prefers it       [Task 2]
              │
              ├── ODF renderers via odfpy                                      [Task 3]
              │
              └── status / Settings: LibreOffice becomes optional              [Task 4]
```

## Task list

### Phase 1: Foundation
- Task 1: Extract the renderers into `office_render.py` (no behaviour change)

### Checkpoint: Foundation
- 851 backend tests still pass; `to_preview` output unchanged

### Phase 2: Move the parse
- Task 2: Render OOXML in the container, with the byte-identical guard

### Checkpoint: Move the parse
- Same HTML from both paths; a sandbox failure yields a notice, not a host parse

### Phase 3: Coverage and honesty
- Task 3: ODT/ODS/ODP via `odfpy`, in the container
- Task 4: Demote LibreOffice from prerequisite to enhancement

### Checkpoint: Complete
- A machine with no LibreOffice previews every supported Office format, in the container,
  and Settings says nothing is missing

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Silent visual regression in the extracted renderers | High | Byte-identical host-vs-container test on real fixtures; extraction is a pure move with no edits |
| Container start latency on every preview (~1–2s) | Medium | Keep the existing in-flight dedup and converted-PDF cache; measure before optimising |
| `_PreviewBudget` and the `_MAX_OFFICE_*` caps are shared with host-side code | Medium | Move them into `office_render.py` and re-export from `filepreview` so existing callers are untouched |
| A machine with no Docker loses Office previews entirely | Medium | Keep the host renderers as the documented, explicit no-image fallback — the same shape as the PDF renderer |
| ODF fidelity is poor enough to be worse than nothing | Low | Ship ODT first, judge the output, and only then decide on ODS/ODP |

## Open questions

- None blocking. LibreOffice's fate was decided: keep it working where present, stop requiring it.
