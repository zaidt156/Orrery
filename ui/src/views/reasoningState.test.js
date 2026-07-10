import assert from "node:assert/strict";
import test from "node:test";

import {
  appendRawThinking,
  applyReasoningEvent,
  createReasoningSnapshot,
  hasReasoning,
  splitInlineThinking,
} from "./reasoningState.js";

test("raw model thinking stays byte-for-byte identical in live and saved state", () => {
  const first = "  first raw line\n";
  const second = "second <tag> & punctuation  ";

  let saved = createReasoningSnapshot();
  saved = applyReasoningEvent(saved, { reasoning_delta: first });
  saved = applyReasoningEvent(saved, { reasoning_delta: second });

  const live = appendRawThinking(
    { role: "assistant", trace: [{ stage: "Routing", status: "done" }] },
    first + second,
  );

  assert.equal(saved.thinking, first + second);
  assert.equal(live.thinking, first + second);
  assert.deepEqual(live.trace, [{ stage: "Routing", status: "done" }]);
  assert.equal(hasReasoning(saved), true);
});

test("dual-shape reasoning steps are saved once", () => {
  const modern = { id: "step-1", stage: "Searching", status: "done" };
  const legacy = { stage: "Searching", status: "done" };

  const saved = applyReasoningEvent(createReasoningSnapshot(), {
    reasoning_step: modern,
    reasoning_event: legacy,
  });

  assert.deepEqual(saved.trace, [modern]);
});

test("inline local-model thinking is separated without rewriting its whitespace", () => {
  const result = splitInlineThinking("before<think>  raw line\nnext  </think>after");

  assert.equal(result.thinking, "  raw line\nnext  ");
  assert.equal(result.body, "beforeafter");
});
