---
name: Document / PDF / Word writing
triggers: pdf, word document, docx, doc file, document, report, essay, letter, memo, whitepaper, white paper, article, paper
---
Use this skill when the user asks for a written document, report, memo, letter, essay, whitepaper, DOCX, or PDF.
Design written content through the `orrery-doc` JSON `sections` array or the configured document artifact mechanism.

## Activation boundary

Do not treat every mention of "paper" or "PDF" as a writing request. If the user asks to analyze, sign, edit,
extract, or verify an existing PDF, follow the relevant file-analysis or artifact-editing path instead.

## Document contract

- **Use a real structure.** Start with a clear title. For longer work, add an introduction, descriptive body
  headings, and a conclusion or next steps.
- **Write substance, not filler.** Every section must add a useful point: evidence, reasoning, examples,
  comparison, recommendation, or implication.
- **Match the format.** A memo, email, essay, report, whitepaper, cover letter, and policy note need different
  tone, length, and structure.
- **Use hierarchy.** Use section levels consistently. Add bullets for scannable lists and tables for comparisons.
- **Be self-contained.** The document should read as a finished deliverable, not a chat transcript. Avoid
  generation disclaimers and meta-commentary.
- **Cite or qualify factual claims.** For current, legal, medical, financial, or technical claims, use reliable
  sources or clearly mark uncertainty.
- **Preserve user constraints.** Honor requested audience, length, language, tone, and required sections.
- **Quality check.** Verify the document has a clear purpose, no contradictions, no missing requested sections,
  and no obvious formatting gaps.
