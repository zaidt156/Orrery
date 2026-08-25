# Office previews without LibreOffice — task list

- [x] **1. Extract the renderers into `backend/features/office_render.py`.** A pure move: the eleven
      renderer functions (`_docx_html`, `_xlsx_html`, `_pptx_html` and their helpers), plus
      `_PreviewBudget` and the six `_MAX_OFFICE_*` caps they read. No host-only imports in the new
      module — it has to be importable inside the container. `filepreview` re-exports what it still
      uses so no other caller changes.
      *Done when:* `to_preview` produces byte-for-byte identical output for a DOCX, an XLSX and a
      PPTX fixture; 851 backend tests pass; `ruff check .` is clean.
      *Scope:* M — 2 files + tests.

- [x] **CHECKPOINT** — pure refactor verified before anything moves into a container.

- [ ] **2. Render OOXML inside the container.** Add `sandbox.render_office_html(name, data)`: ship
      `office_render.py` in as a read-only input file, `sys.path` it, run it, return the HTML as one
      output file. `to_preview` prefers the container whenever `sandbox.image_ready()`, and a
      `SandboxError` yields the inert notice — never a host parse. Host renderers remain the
      explicit fallback only when no image exists.
      *Done when:* a test renders the same fixture through both paths and asserts the HTML is
      byte-identical; a failing container produces a notice and provably no host parse; a real
      container run renders all three formats.
      *Scope:* M — 3 files + tests.

- [ ] **CHECKPOINT** — the last in-process parse of untrusted Office files is gone.

- [ ] **3. ODT/ODS/ODP via `odfpy`.** Already in the image, currently unused. Render in the
      container like the OOXML formats. Add the extensions to `is_office_file` and to the preview
      dispatch. Start with ODT, judge the output, then decide on ODS/ODP.
      *Done when:* an `.odt` previews as formatted HTML instead of "Preview unavailable for this
      file type"; TODO.md's claim that the converter covers ODF is corrected.
      *Scope:* M — 3 files + tests.

- [ ] **4. Demote LibreOffice from prerequisite to enhancement.** `office_preview_status()` stops
      reporting `available: false` when only LibreOffice is missing — the container is a renderer.
      Settings stops implying previews are broken; the install action becomes optional polish for
      page-faithful output. `routes_files.py` renderer labels reflect the container path.
      *Done when:* on a machine with Docker and no LibreOffice, Settings reports Office previews as
      working and offers the install as an upgrade, not a fix.
      *Scope:* S/M — 3 files + tests.

- [ ] **CHECKPOINT** — fresh machine, no LibreOffice: every supported Office format previews, the
      parse happens in the container, and nothing in the UI claims something is missing.

- [ ] **5. Reconcile the documents.** ARCHITECTURE.md §11 and the Office-preview section, TODO.md's
      two Workstream 2 items, PLAN.md's Workstream 2 checkpoint, and an ADR recording why the
      renderers moved rather than being rewritten. Append a DEVLOG entry.
      *Done when:* no canonical document still says Office previews need LibreOffice or that ODF is
      covered by the converter.
      *Scope:* S — docs only.
