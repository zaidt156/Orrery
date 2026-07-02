---
name: PowerPoint / slide deck design
triggers: powerpoint, power point, pptx, ppt, slide deck, slidedeck, pitch deck, sales deck, presentation, slides, keynote
---
Use this skill when the user asks for a presentation or slide deck. Design a real deck through the
`orrery-doc` JSON `slides` array or the configured slide artifact mechanism.

## Activation boundary

Do not activate for unrelated uses of "deck" such as card decks, patios, or design decks unless the user clearly
means a presentation.

## Deck contract

- **One idea per slide.** Each slide must have a specific title and a single purpose.
- **Useful structure.** Start with a strong title slide. For decks over four slides, include an agenda near the
  front and a takeaways/next-steps slide near the end. If no slide count is given, default to 8–12 slides scaled
  to the topic and say so.
- **Respect slide count.** If the user asks for a number of slides, treat it as the total slide count unless they
  explicitly say "content slides" or "excluding title."
- **Keep text presentable.** Use 3–6 concise bullets per content slide, roughly 40 words maximum — audiences read
  slides or listen to the speaker, not both. Prefer one-line bullets. Avoid paragraphs.
- **Use speaker notes.** Add short, practical notes for each slide explaining what the presenter should say.
- **Make it visual.** Include chart, diagram, table, image, or layout suggestions where they improve
  understanding, and specify the data or comparison each chart should show.
- **Keep design consistent.** Use one coherent color set and at most two font roles (heading, body) across the
  deck; assume 16:9 unless told otherwise.
- **Avoid filler.** No generic "Introduction" titles, repeated bullets, vague benefits, or text walls.
- **Match the audience.** Adjust depth, tone, and terminology to the audience: executive, technical, academic,
  sales, training, or classroom.
- **Final quality check.** Verify the deck has a clear story: problem/context → key points → evidence/examples →
  recommendation or takeaway. Fix gaps before returning.
