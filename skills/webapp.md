---
name: Self-contained HTML / web app artifacts
triggers: html, webpage, web page, website, landing page, single-page app, interactive page, dashboard mockup
---
Use this skill when the user asks for a downloadable or previewable HTML page, small web app, landing page,
interactive demo, or dashboard mockup.

## Web artifact contract

- **One self-contained file.** Create a complete `.html` file with inline CSS and JavaScript.
- **No external dependencies.** Do not use CDNs, remote images, remote fonts, network fetches, iframes, or links
  needed for rendering. The preview must work offline inside Orrery.
- **Use real layout.** Include semantic structure, responsive sizing, accessible labels, polished spacing, and a
  coherent visual hierarchy.
- **Make interaction work.** If the user asks for buttons, controls, animation, calculators, filters, or a small
  app, implement the JavaScript behavior in the file.
- **Avoid placeholders.** Use complete content and realistic sample data when requested. Do not leave TODOs,
  lorem ipsum, broken images, or empty panels.
- **Validate before returning.** Reopen or parse the generated HTML, check that it contains body content, and
  ensure there are no external script/style/image references.
