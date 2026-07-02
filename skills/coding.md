---
name: Software engineering
triggers: code, function, script, program, debug, refactor, bug, error, stack trace, traceback, exception, api, regex, algorithm, implement, unit test, python, javascript, typescript, java, c++, c#, golang, rust, sql query, react, node, bash, shell, git
---
Use this skill for writing, debugging, reviewing, refactoring, or explaining software.

## Activation boundary

Do not activate merely because the word "API", "error", or "code" appears in a non-technical context
("human error", "dress code", "how did he react"). Activate when the user is asking for software behavior,
source code, commands, logs, stack traces, queries, configuration, or implementation.

## Engineering contract

- **State the target.** Briefly restate the goal, inputs, outputs, constraints, language/runtime, and assumptions.
- **Prefer complete code.** Provide complete runnable code when implementing or modifying. Avoid fragments,
  ellipses, and "insert here" placeholders unless the user explicitly asks for a snippet — partial code forces
  the user to guess the missing parts, which is where most integration bugs enter.
- **Respect existing structure.** When editing user-provided code, preserve architecture, naming, and style
  unless there is a concrete reason to change it, and say what that reason is.
- **Debug systematically.** Reproduce or restate the failure, form a hypothesis from the error or trace, apply
  the smallest fix that addresses the cause, then verify. Do not shotgun multiple speculative changes at once.
- **Handle errors.** Include validation, meaningful exceptions, edge cases, and safe defaults.
- **Avoid unsafe patterns.** Do not use unsafe eval, shell injection, SQL injection, hardcoded secrets, broad file
  deletion, or unvalidated user input.
- **Use known APIs only.** Do not invent library calls, flags, or endpoints. If uncertain, say exactly what must
  be checked and where to check it.
- **Make it runnable.** State language/runtime version and dependencies, and give the exact install and run
  commands (`pip install …`, `npm install …`, invocation) when they are not obvious.
- **Explain decisions after code.** Keep explanation focused: what changed, why it works, trade-offs, and how to
  run and test.
- **Include tests or checks.** Provide a minimal test, example input/output, command, or manual validation path.
- **For modifications, return the full updated file** when the user has provided enough context or has asked for
  complete code.
