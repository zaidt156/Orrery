---
name: Self-contained HTML / web app artifacts
triggers: html, webpage, web page, website, landing page, single-page app, interactive page, dashboard mockup, web app, calculator app, browser game, html game, prototype, portfolio site
---
Use this skill when the user asks for a downloadable or previewable HTML page, small web app, landing page,
interactive demo, or dashboard mockup.

## Activation boundary

This skill produces static, self-contained pages. If the request needs a backend, database, authentication, or
live external data, use the software engineering skill for that part and offer a static demo version here,
stating the difference.

## Web artifact contract

- **One self-contained file.** Create a complete `.html` file — with `<!doctype html>` and a viewport meta tag —
  with inline CSS and JavaScript.
- **No external dependencies.** Do not use CDNs, remote images, remote fonts, network fetches, iframes, or links
  needed for rendering. Use system font stacks and inline SVG or data URIs for graphics; the preview must work
  fully offline inside Orrery.
- **Use real layout.** Include semantic structure, responsive sizing, accessible labels, keyboard-usable controls
  with visible focus states, polished spacing, and a coherent visual hierarchy.
- **Make interaction work.** If the user asks for buttons, controls, animation, calculators, filters, or a small
  app, implement the JavaScript behavior in the file and handle empty or invalid input states.
- **Avoid placeholders.** Use complete content and realistic sample data when requested. Do not leave TODOs,
  lorem ipsum, broken images, or empty panels.
- **Validate before returning.** Reopen or parse the generated HTML: confirm it contains body content, has no
  external script/style/image references, and that interactive elements have their handlers wired up. Fix
  failures before returning.
