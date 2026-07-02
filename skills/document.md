---
name: Document / PDF / Word writing
triggers: pdf, word document, docx, doc file, document, report, essay, letter, memo, whitepaper, white paper, article, paper, cover letter, resume, cv, proposal, one-pager, meeting minutes, press release, blog post, speech
---
Use this skill when the user asks for a written document, report, memo, letter, essay, whitepaper, DOCX, or PDF.
Design written content through the `orrery-doc` JSON `sections` array or the configured document artifact mechanism.

## Activation boundary

Do not treat every mention of "paper" or "PDF" as a writing request. If the user asks to analyze, sign, edit,
extract, or verify an existing PDF, follow the relevant file-analysis or artifact-editing path instead. A "speech"
here means text to be delivered by a person; converting text into spoken audio belongs to the audio skill.

## Document contract

- **Use a real structure.** Start with a clear title. For longer work, add an introduction, descriptive body
  headings, and a conclusion or next steps.
- **Write substance, not filler.** Every section must add a useful point: evidence, reasoning, examples,
  comparison, recommendation, or implication.
- **Match the format.** A memo, email, essay, report, whitepaper, cover letter, CV, and policy note need
  different tone, length, and structure. State the assumed audience and target length if the user did not
  give them.
- **Prose first for narrative documents.** Reports, essays, and letters read as connected paragraphs; reserve
  bullets for genuinely list-like content and tables for comparisons. A bullet-only document reads as an
  outline, not a finished deliverable.
- **Use hierarchy.** Use section levels consistently. Add bullets for scannable lists and tables for comparisons.
- **Be self-contained.** The document should read as a finished deliverable, not a chat transcript. Avoid
  generation disclaimers and meta-commentary.
- **Cite or qualify factual claims.** For current, legal, medical, financial, or technical claims, use reliable
  sources or clearly mark uncertainty. Never invent citations.
- **Preserve user constraints.** Honor requested audience, length, language, tone, and required sections.
- **Quality check before returning.** Re-read the draft once against the request: clear purpose, no
  contradictions, no missing requested sections, no formatting gaps. Fix what fails, then deliver.
