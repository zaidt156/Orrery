import { test } from "node:test";
import assert from "node:assert/strict";

import { contextOptionsFor, fmtTokens, modelCtx, DEFAULT_CONTEXT } from "./contextTiers.js";

const values = (opts) => opts.map(([v]) => Number(v));

test("the list ends at the model's real maximum and never above it", () => {
  // Every size offered here is one the backend accepts and then silently clamps, so a size the
  // model doesn't have looks to the user like it worked.
  const opts = contextOptionsFor(200000);
  assert.ok(Math.max(...values(opts)) === 200000);
  assert.ok(!values(opts).includes(1000000));
  assert.match(opts[opts.length - 1][1], /\(max\)$/);
});

test("a 1M-class model still gets the steps below it", () => {
  assert.deepEqual(values(contextOptionsFor(1048576)),
    [32768, 65536, 131072, 262144, 524288, 1000000, 1048576]);
});

test("a 10M model does not jump straight from 1M to its maximum", () => {
  // Llama 4 Scout is an order of magnitude past everything else; without the higher steps the
  // selector offered 1M and then 10M with nothing usable in between.
  const v = values(contextOptionsFor(10000000));
  assert.ok(v.includes(2000000) && v.includes(4000000));
  assert.equal(v[v.length - 1], 10000000);
});

test("a tiny local model gets its maximum and nothing else", () => {
  assert.deepEqual(values(contextOptionsFor(32768)), [32768]);
});

test("labels name the window the model actually has", () => {
  assert.equal(fmtTokens(131072), "128K");
  assert.equal(fmtTokens(1000000), "1M");
  assert.equal(fmtTokens(10000000), "10M");
  // Rounding 1,048,576 up to "1.1M" would put a window on screen that doesn't exist.
  assert.equal(fmtTokens(1048576), "1.05M");
  assert.equal(fmtTokens(1050000), "1.05M");
});

test("an unknown model falls back rather than showing nothing", () => {
  assert.equal(modelCtx([{ id: "a", context_window: 200000 }], "a"), 200000);
  assert.equal(modelCtx([], "missing"), DEFAULT_CONTEXT);
  assert.equal(modelCtx(undefined, "missing"), DEFAULT_CONTEXT);
});
