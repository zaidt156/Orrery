---
name: Sandboxed artifact creation
triggers: sandbox, compute, calculation, chart, graph, plot, simulation, generate file, build file, downloadable file, zip, package
---
Use this skill when code execution is needed to create, transform, validate, or package a deliverable.

## Relationship to other artifact skills

Specialist skills define the content and structure:
- slide requests use the presentation skill;
- spreadsheet requests use the spreadsheet skill;
- document/PDF/Word requests use the document skill;
- image/SVG/visual requests use the visual skill;
- audio requests use the audio skill.

This sandbox skill handles implementation, validation, and packaging when code is required.

## Sandbox contract

- **One complete program.** Write one complete Python program or equivalent script that creates the requested
  deliverables.
- **Save to `./out`.** All user-visible outputs must be written under `./out` or the configured artifact output
  directory. Do not scatter files across the workspace.
- **No hidden dependencies.** Do not use the network, browser automation, private APIs, localhost services,
  secret files, or undeclared local paths.
- **Validate before returning.** Re-open or inspect created files where possible: check file existence, non-zero
  size, valid format, sheet names, slide count, audio duration, image dimensions, or archive contents.
- **Return only requested file types.** Do not create companion exports unless the user asks for them or they are
  needed for validation.
- **Quality is required.** No empty shells, placeholder rows, repeated generic slides, blank images, silent
  failures, or fake validation messages.
- **Report limitations.** If a library cannot produce an exact requested format, state the closest valid output
  and the trade-off.
