import assert from "node:assert/strict";
import test from "node:test";

import {
  appendDeltaToThread,
  createClientMessage,
  messageKey,
  messageRowPropsEqual,
} from "./chatThread.js";


test("a streamed delta preserves every completed row identity", () => {
  const completed = Array.from({ length: 100 }, (_, index) => ({
    id: `message-${index}`,
    role: index % 2 ? "assistant" : "user",
    content: `completed ${index}`,
  }));
  const active = createClientMessage({ role: "assistant", content: "hel", streaming: true });
  const before = [...completed, active];

  const after = appendDeltaToThread(before, "lo");

  assert.equal(after.length, 101);
  for (let index = 0; index < completed.length; index += 1) {
    assert.equal(after[index], before[index]);
  }
  assert.notEqual(after[100], before[100]);
  assert.equal(after[100].content, "hello");
  assert.equal(messageKey(after[100], 100), messageKey(before[100], 100));
});


test("message row comparison skips unchanged rows and renders changed rows", () => {
  const message = { id: "message-1", role: "assistant", content: "done" };
  const actions = { current: {} };
  const base = {
    message,
    index: 1,
    isLast: false,
    sending: true,
    copied: false,
    activeId: "conversation-1",
    activeTitle: "Chat",
    precedingPrompt: "",
    lastPrompt: null,
    actions,
  };

  assert.equal(messageRowPropsEqual(base, { ...base }), true);
  assert.equal(messageRowPropsEqual(base, { ...base, message: { ...message, content: "changed" } }), false);
  assert.equal(messageRowPropsEqual(base, { ...base, sending: false }), false);
  assert.equal(messageRowPropsEqual(base, { ...base, copied: true }), false);
});


test("a 100-message thread invalidates only its active row for a token delta", () => {
  const completed = Array.from({ length: 100 }, (_, index) => ({
    id: `message-${index}`,
    role: index % 2 ? "assistant" : "user",
    content: `completed ${index}`,
  }));
  const active = createClientMessage({ role: "assistant", content: "a", streaming: true });
  const before = [...completed, active];
  const after = appendDeltaToThread(before, "b");
  const actions = { current: {} };
  const rowProps = (messages, index) => ({
    message: messages[index],
    index,
    isLast: index === messages.length - 1,
    sending: true,
    copied: false,
    activeId: "conversation-1",
    activeTitle: "Long chat",
    precedingPrompt: index ? "nearest prompt" : "",
    lastPrompt: index ? messages[index - (index % 2 || 1)] : null,
    actions,
  });

  const invalidatedRows = before
    .map((_, index) => messageRowPropsEqual(rowProps(before, index), rowProps(after, index)))
    .flatMap((unchanged, index) => (unchanged ? [] : [index]));

  assert.deepEqual(invalidatedRows, [100]);
});


test("new local messages receive stable distinct client keys", () => {
  const first = createClientMessage({ role: "user", content: "one" });
  const second = createClientMessage({ role: "assistant", content: "two", streaming: true });

  assert.match(messageKey(first, 0), /^local-message-/);
  assert.notEqual(messageKey(first, 0), messageKey(second, 1));
  assert.equal(messageKey(first, 99), messageKey(first, 0));
});
