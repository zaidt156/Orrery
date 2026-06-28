---
name: Code-rendered images and visual artifacts
triggers: image, illustration, diagram, poster, icon, logo, visual, infographic, svg, vector, banner, thumbnail, cover art
---
Use this skill for deterministic visual artifacts such as SVGs, diagrams, posters, icons, logos, thumbnails,
banners, and code-rendered images.

## Activation boundary

Use this for code-rendered or structured visual outputs. If the environment has a separate image-generation or
photo-editing capability and the user asks for a realistic generated/edited image, use that capability instead.

## Visual contract

- **Define the composition.** Identify canvas size, subject, layout, hierarchy, colors, typography, and visual
  style before producing the asset.
- **Make the visual useful.** Prefer a real object, diagram, scene, emblem, or infographic over decorative text.
- **No accidental text.** Do not write the user's prompt into the image unless visible words, labels, or a wordmark
  are explicitly requested.
- **Keep SVG self-contained.** Use shapes, paths, gradients, and embedded-safe text only when requested. Avoid
  external images, fonts, scripts, or network assets.
- **Design for the use case.** Icons must work small. Thumbnails need strong contrast and focal point. Diagrams
  need readable labels and logical flow.
- **Respect brand constraints.** Preserve requested colors, style rules, stroke widths, spacing, and export format.
- **Validate output.** Check that the file renders, has non-zero size, correct dimensions, and no missing assets.
