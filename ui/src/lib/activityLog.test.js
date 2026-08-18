import assert from "node:assert/strict";
import test from "node:test";

import { ACTIVITY_LIMIT, applyActivityEvent, elapsedLabel } from "./activityLog.js";

const fold = (events, start = 1000) =>
  events.reduce((log, ev, i) => applyActivityEvent(log, ev, start + i), []);

test("token-level deltas fold into one growing entry instead of flooding the log", () => {
  const log = fold([{ delta: "Hel" }, { delta: "lo " }, { delta: "world" }]);

  assert.equal(log.length, 1);
  assert.equal(log[0].kind, "answer");
  assert.equal(log[0].chars, 11);
  assert.match(log[0].text, /11 characters/);
});

test("thinking and answer are separate running entries", () => {
  const log = fold([{ reasoning_delta: "hmm" }, { delta: "answer" }, { delta: "!" }]);

  assert.deepEqual(log.map((e) => e.kind), ["thinking", "answer"]);
  assert.equal(log[0].chars, 3);
  assert.equal(log[1].chars, 7);
});

test("a status step is recorded verbatim", () => {
  const log = fold([{ status: "Searching your documents…" }]);

  assert.equal(log[0].kind, "status");
  assert.equal(log[0].text, "Searching your documents…");
});

test("retrieval reports how many sources actually came back", () => {
  const log = fold([{ sources: ["a.pdf", "b.md"] }]);

  assert.equal(log[0].kind, "sources");
  assert.match(log[0].text, /Retrieved 2 sources/);
});

test("one source is not pluralised", () => {
  const log = fold([{ sources: ["only.pdf"] }]);
  assert.match(log[0].text, /Retrieved 1 source$/);
});

test("an approval request is flagged for attention, and its resolution recorded", () => {
  const log = fold([
    { approval: { tool: "run_shell" } },
    { approval_resolved: { id: "x", status: "approved" } },
  ]);

  assert.equal(log[0].kind, "approval");
  assert.match(log[0].text, /run_shell/);
  assert.equal(log[0].tone, "warn");
  assert.equal(log[1].tone, "ok");
});

test("errors are toned as errors so they are visible in a long log", () => {
  const log = fold([{ error: "The provider refused the request." }]);

  assert.equal(log[0].kind, "error");
  assert.equal(log[0].tone, "error");
});

test("created files are named when the event carries names", () => {
  const log = fold([{ files: [{ name: "report.pdf" }, { name: "data.xlsx" }] }]);

  assert.match(log[0].text, /report\.pdf/);
  assert.match(log[0].text, /data\.xlsx/);
});

test("token usage is summarised", () => {
  const log = fold([{ message_usage: { tokens_in: 1200, tokens_out: 340 } }]);

  assert.match(log[0].text, /1200 in/);
  assert.match(log[0].text, /340 out/);
});

test("events the log has nothing to say about are ignored, not blank lines", () => {
  const log = fold([{ message_id: "abc" }, { title: "A chat" }]);
  assert.equal(log.length, 0);
});

test("the input log is never mutated", () => {
  const first = applyActivityEvent([], { status: "one" }, 1);
  const second = applyActivityEvent(first, { status: "two" }, 2);

  assert.equal(first.length, 1);
  assert.equal(second.length, 2);
});

test("a very long turn stops growing without bound", () => {
  let log = [];
  for (let i = 0; i < ACTIVITY_LIMIT + 50; i += 1) {
    log = applyActivityEvent(log, { status: `step ${i}` }, i);
  }

  assert.equal(log.length, ACTIVITY_LIMIT);
  assert.match(log[log.length - 1].text, new RegExp(`step ${ACTIVITY_LIMIT + 49}$`));
});

test("elapsed labels are relative to the start of the turn", () => {
  assert.equal(elapsedLabel(1500, 1000), "0.5s");
  assert.equal(elapsedLabel(1000, 1000), "0.0s");
  assert.equal(elapsedLabel(500, 1000), "0.0s");   // never negative
});
