---
name: Sandboxed artifact creation
triggers: sandbox, compute, calculation, chart, graph, plot, simulation, generate file, build file, powerpoint, pptx, xlsx, pdf, wav, zip
---
When a request requires code to create an artifact, use the sandbox contract.

- Write one complete Python program that saves requested deliverables into `./out`.
- Do not use the network, browser automation, private web APIs, hidden sessions, or local host files.
- Validate the output inside the program when the library supports it, then let Orrery perform backend validation too.
- Produce only the requested file types unless the user explicitly asks for companion exports.
- Treat quality as part of correctness: no placeholders, no empty shells, no repeated generic slides, and no thin content.
