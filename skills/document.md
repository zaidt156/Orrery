---
name: Document / PDF / Word writing
triggers: pdf, word document, docx, doc file, document, report, essay, letter, memo, whitepaper, white paper, article, paper
---
When the request is a written document, design it via the `orrery-doc` JSON `sections` array (see the
FILES instruction for the schema). Write a real, well-structured document:

- **Logical structure.** Start with a clear title and, for longer docs, a short intro. Break the body
  into sections with descriptive `heading`s (set `level` 1–3 for hierarchy). End with a conclusion or
  summary when appropriate.
- **Substance over filler.** Each section's `paragraphs` should make real points with specifics,
  examples, and (where relevant) data — not generic padding. Use `bullets` for lists and a `table`
  when comparing things.
- **Right length and tone.** Match the depth and register the user asked for (a one-page memo vs. a
  detailed report; formal vs. casual). If they specify a length, honor it.
- **Self-contained.** The document should read well on its own, with no chat-style asides, no "as an
  AI", and no references to this being generated.
