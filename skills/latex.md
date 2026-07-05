---
name: LaTeX / TeX source documents
triggers: latex, tex, .tex, latex source, latex document, latex template, equation, academic paper, cv template, resume template
---
Use this skill when the requested deliverable is LaTeX or TeX source. Orrery v1 treats TeX as
source-first: create a complete `.tex` file and validate it as UTF-8 text. Do not assume a local
TeX compiler is installed.

## Contract

- Produce a complete source file, not fragments. Include `\documentclass`, a preamble, `\begin{document}`,
  useful structure, and `\end{document}`.
- Match the requested genre: resume/CV, academic-style report, template, equation sheet, table-heavy
  handout, letter, or article should use appropriate sections and packages.
- Keep it portable. Use standard packages only and avoid shell escape, absolute paths, host paths,
  remote files, or `\input` / `\include` references to files that are not generated alongside it.
- Avoid placeholders. Do not use TODO, lorem ipsum, `[Name]`, `[Date]`, or generic sample content unless
  the user explicitly asked for a blank template.
- If the user asks for a PDF compiled from LaTeX, generate the `.tex` source and a normal Orrery PDF
  separately unless a configured remote compile tool is available.

## Quality bar

- For resumes/CVs, build a clean ATS-friendly layout with real sections and concise bullets.
- For academic/report content, use hierarchy, equations only where useful, and tables for structured data.
- For templates, make every fillable area clearly intentional and keep the file compilable after edits.
