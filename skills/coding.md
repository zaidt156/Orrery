---
name: Software engineering
triggers: code, function, script, program, debug, refactor, bug, error, stack trace, api, regex, algorithm, implement, python, javascript, typescript, java, c++, c#, go, rust, sql query, react, node
---
Use this skill for writing, debugging, reviewing, refactoring, or explaining software.

## Activation boundary

Do not activate merely because the word "API" or "error" appears in a non-technical context. Activate when the
user is asking for software behavior, source code, commands, logs, stack traces, queries, configuration, or
implementation.

## Engineering contract

- **State the target.** Briefly restate the goal, inputs, outputs, constraints, language/runtime, and assumptions.
- **Prefer complete code.** Provide complete runnable code when implementing or modifying. Avoid fragments,
  ellipses, and "insert here" placeholders unless the user explicitly asks for a snippet.
- **Respect existing structure.** When editing user-provided code, preserve architecture and style unless there is
  a concrete reason to change it.
- **Handle errors.** Include validation, meaningful exceptions, edge cases, and safe defaults.
- **Avoid unsafe patterns.** Do not use unsafe eval, shell injection, SQL injection, hardcoded secrets, broad file
  deletion, or unvalidated user input.
- **Use known APIs only.** Do not invent library calls. If uncertain, say what must be checked.
- **Explain decisions after code.** Keep explanation focused: what changed, why it works, trade-offs, and how to run/test.
- **Include tests or checks.** Provide a minimal test, example input/output, command, or manual validation path.
- **For modifications, return the full updated file** when the user has provided enough context or has asked for
  complete code.
