---
name: Sandboxed artifact creation
triggers: sandbox, compute, calculation, chart, graph, plot, simulation, run code, execute, convert file, generate file, build file, downloadable file, export, zip, package
---
Use this skill when code execution is needed to create, transform, validate, or package a deliverable.

## Activation boundary

Activate when the request needs code to run or a file to exist: generating, converting, computing over data,
or packaging. Do not activate for explaining a formula, method, or concept where a written answer suffices —
"how do I calculate compound interest" needs an explanation; "calculate this and give me a chart" needs the
sandbox.

## Relationship to other artifact skills

Specialist skills define the content and structure:
- slide requests use the presentation skill;
- spreadsheet requests use the spreadsheet skill;
- document/PDF/Word requests use the document skill;
- image/SVG/visual requests use the visual skill;
- audio requests use the audio skill;
- video/animation requests use the video skill;
- HTML/web app requests use the web artifact skill.

This sandbox skill handles implementation, validation, and packaging when code is required.

## Sandbox contract

- **One complete program.** Write one complete Python program or equivalent script that creates the requested
  deliverables.
- **Save to `./out`.** All user-visible outputs must be written under `./out` or the configured artifact output
  directory. Do not scatter files across the workspace.
- **No hidden dependencies.** Do not use the network, browser automation, private APIs, localhost services,
  secret files, or undeclared local paths.
- **Make runs reproducible.** Seed any randomness and avoid time-dependent output unless the user wants it,
  so a re-run produces the same deliverable.
- **Validate before returning.** Re-open or inspect created files where possible: check file existence, non-zero
  size, valid format, sheet names, slide count, audio duration, image dimensions, or archive contents. If a
  check fails, fix and re-validate instead of returning the broken file.
- **Report what was produced.** End with a short manifest: each file's name, type, size, and one-line purpose.
- **Return only requested file types.** Do not create companion exports unless the user asks for them or they are
  needed for validation.
- **Quality is required.** No empty shells, placeholder rows, repeated generic slides, blank images, silent
  failures, or fake validation messages.
- **Report limitations.** If a library cannot produce an exact requested format, state the closest valid output
  and the trade-off.
