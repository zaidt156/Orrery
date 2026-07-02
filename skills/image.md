---
name: Code-rendered images and visual artifacts
triggers: image, illustration, diagram, poster, icon, logo, visual, infographic, svg, vector, banner, thumbnail, cover art, favicon, wordmark, badge, flowchart, emblem
---
Use this skill for deterministic visual artifacts such as SVGs, diagrams, posters, icons, logos, thumbnails,
banners, and code-rendered images.

## Activation boundary

Use this for code-rendered or structured visual outputs. If the environment has a separate image-generation or
photo-editing capability and the user asks for a realistic generated/edited image, use that capability instead.
Data-driven charts and plots follow the sandbox/spreadsheet path; this skill covers illustrative and structural
visuals.

## Visual contract

- **Define the composition.** Identify canvas size, subject, layout, hierarchy, colors, typography, and visual
  style before producing the asset.
- **Make the visual useful.** Prefer a real object, diagram, scene, emblem, or infographic over decorative text.
- **No accidental text.** Do not write the user's prompt into the image unless visible words, labels, or a wordmark
  are explicitly requested.
- **Keep SVG self-contained and scalable.** Give the root `<svg>` a `viewBox` so it scales cleanly at any size.
  Use shapes, paths, and gradients; add text only when requested. Avoid external images, fonts, scripts, or
  network assets, and stick to generic font families (sans-serif, serif, monospace) so text renders the same
  everywhere.
- **Design for the use case.** Icons must stay legible at 16–24 px, so limit detail and use bold silhouettes.
  Thumbnails need strong contrast and one focal point. Diagrams need readable labels, adequate spacing, and a
  logical left-to-right or top-down flow with no overlapping elements.
- **Respect brand constraints.** Preserve requested colors, style rules, stroke widths, spacing, and export format.
- **Validate output.** Render or parse the file: check it is well-formed, has non-zero size, correct
  dimensions/viewBox, no external references, and no text overflowing its container. Fix failures before
  returning.
