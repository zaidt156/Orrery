---
name: PowerPoint / slide deck design
triggers: powerpoint, power point, pptx, ppt, slide deck, slidedeck, presentation, slides, deck, keynote
---
When the request is a presentation, design a real deck via the `orrery-doc` JSON `slides` array
(see the FILES instruction for the exact schema). Make it presentation-quality, not a wall of text:

- **One idea per slide.** Each slide gets a clear, specific title (not "Introduction" — say what it
  introduces) and 3–6 concise bullet points. Keep bullets to one line where possible; no paragraphs.
- **Open and close well.** Start with a title slide (use `title` + `subtitle`). If the deck is more
  than ~4 slides, add an agenda/overview slide near the front and a summary or "key takeaways" slide
  at the end.
- **Right length.** If the user asks for N slides/pages, produce N content slides (plus the title
  slide). If they don't say, pick a sensible number for the topic (usually 6–12).
- **Speaker notes.** Add a short `notes` field per slide with what a presenter would say — it makes
  the deck genuinely usable.
- Use parallel phrasing across bullets, lead with the point, and prefer concrete facts/numbers.
