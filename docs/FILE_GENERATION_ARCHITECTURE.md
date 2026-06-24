# Orrery — File Generation Architecture (open-source)

This is the authoritative spec for "generate any file type" in Orrery. Mechanism:

> A **skill** teaches the model *how* to make a file type well → the model **writes code**
> using real OSS libraries → the code runs in an **isolated sandbox** → the resulting **file**
> is written to an outputs folder and saved to the user's library.

No "file model." Files are produced by running ordinary code (`python-docx`, `openpyxl`,
`python-pptx`, `reportlab`/`fpdf2`, `matplotlib`, `pandas`, `Pillow`, …). Exposed as ONE tool,
`file.generate`, in the shared tool registry, so Chat, Automations, and Agents all share it.

## Three components
1. **Skills** — `skills/<type>/SKILL.md` (frontmatter: name, description/triggers) + optional
   `scripts/` and `references/`. Progressive disclosure: only the selected skill is loaded per
   request. Selection by description/keyword match (model may confirm). Adding a format = a new
   skill folder, no core change.
2. **Execution sandbox** — pluggable `Executor` Protocol, strongest available chosen at runtime:
   - **Docker** (default): pre-baked image; per run `--network none`, read-only root + tmpfs/
     mounted workspace, non-root, `--cap-drop ALL`, `--pids-limit`, CPU/mem/time caps, only the
     run's I/O dirs mounted.
   - **Pyodide/WASM** (no-Docker strong option, later): pure-Python file libs run in-browser.
   - **Subprocess** (fallback): OS resource limits, no env/secrets, network off.
   Non-negotiable floor (security.md §5): no network, no secrets/keychain/DB, FS restricted to the
   three dirs, resource caps, non-root. The sandbox is the protection — never trust the code.
3. **File I/O** — three dirs per run: `inputs/` (read-only sources), `workspace/` (scratch),
   `outputs/` (deliverables — the only place the model writes). Output contract: model writes to
   the outputs dir and prints a manifest of filenames; runner validates (exists, size/type/count
   caps) and registers. Files live **on disk**; only metadata in Postgres
   (`id,name,type,size,source_request,skill_used,model_used,run_id,path,created_at,tags`).

## The generation loop (`file.generate`)
resolve inputs & select skill(s) → assemble prompt (SKILL.md + request + inputs + output
contract, structured output) → run code in sandbox → **on error feed traceback back, retry ≤3** →
validate outputs → register in library → return manifest. Heavy runs go through the queue
(Procrastinate) for durability.

## Library set (all OSS, pre-baked into the sandbox image)
docx→python-docx · xlsx→openpyxl/XlsxWriter · pptx→python-pptx · pdf→fpdf2/reportlab (weasyprint
for HTML→PDF) · charts→matplotlib/plotly · data→pandas · images→Pillow · csv/json/xml/yaml→stdlib
+PyYAML · md/html→markdown/Jinja2 · convert→pypandoc · archives→zipfile/tarfile.

## Security (security.md §5/§6/§10)
Isolation first (code only ever runs in the sandbox). Inputs are untrusted data, not instructions.
No ambient DB/keychain access — if a run needs DB data, the backend fetches it read-only with PII
redaction and drops a file in `inputs/`. Validate/contain outputs; never auto-open/execute. Bounded
retries + total runtime. Audit skill/model/code-hash/runtime/exit/manifest — never secrets or raw data.

## Milestones
1. Executor interface + Docker impl (I/O dirs + caps). 2. Skill loader + registry (SKILL.md,
progressive disclosure). 3. Seed skills: docx, xlsx, pptx, pdf, chart/data. 4. `file.generate`
tool with plan→code→run→fix loop. 5. Library storage (disk + Postgres) + UI, pin-to-Chat.
6. Wire into Chat (`/file`), an Automation node, a scope-gated Agent capability. 7. Harden: add
Pyodide; output validation. 8. Document in `orrery-development` + `security.md`.

---
## Implementation status (2026-06-23)
- **Done & verified:** Docker sandbox image `orrery-sandbox:latest` (Dockerfile in `sandbox/`) with
  the OSS lib set; `backend/features/sandbox.py` runs code with `--network none`, mem/cpu/pids caps,
  read-only root + tmpfs, non-root, `--cap-drop ALL`, `no-new-privileges`, 60s timeout; collects
  files from `/work/out`. Smoke-tested: produced a real PPTX, XLSX, and matplotlib PNG by running code.
- **Done:** skill loader `backend/features/skills.py` (flat `*.md` + open `*/SKILL.md`), seed skills
  in `skills/` (core/coding/powerpoint/spreadsheet/document); injected into chat per request.
- **Interim (no-Docker path):** `backend/features/docgen.py` builds real PPTX/XLSX/DOCX/PDF from a
  model `orrery-doc` JSON spec. Keep as the fallback when the sandbox isn't available.
- **Next:** `file.generate` tool + plan→code→run→fix loop wired into Chat; inputs/workspace/outputs
  + manifest; library storage (disk + Postgres) + UI; Automation node + Agent capability; Pyodide.
