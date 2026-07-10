import assert from "node:assert/strict";
import test from "node:test";

import { dayBuckets, sparkPoints } from "./spark.js";

test("sparkPoints maps a series across the box, higher value = smaller y", () => {
  const pts = sparkPoints([0, 10], 100, 30, 2);
  const [first, last] = pts.split(" ").map((p) => p.split(",").map(Number));
  assert.equal(first[0], 2);            // starts at left pad
  assert.equal(last[0], 98);            // ends at right pad
  assert.ok(first[1] > last[1]);        // 0 sits lower than 10
});

test("sparkPoints handles empty and single-point series", () => {
  assert.equal(sparkPoints([]), "");
  const pts = sparkPoints([5], 100, 30, 2);
  assert.ok(pts.split(" ").length >= 2); // a single value still draws a visible line
});

test("sparkPoints draws a flat midline for an all-equal series", () => {
  const ys = sparkPoints([3, 3, 3], 100, 30, 2).split(" ").map((p) => Number(p.split(",")[1]));
  assert.ok(ys.every((y) => y === ys[0]));
  assert.ok(ys[0] > 0 && ys[0] < 30);
});

test("dayBuckets counts timestamps into trailing LOCAL daily buckets", () => {
  const now = new Date(2026, 6, 10, 12, 0, 0); // local noon, July 10
  const iso = (d) => d.toISOString();
  const stamps = [
    iso(new Date(2026, 6, 10, 9)), iso(new Date(2026, 6, 10, 1)),  // today ×2
    iso(new Date(2026, 6, 9, 15)),                                  // yesterday ×1
    iso(new Date(2026, 5, 1)),                                      // far outside the window
    "not a date",
  ];
  const buckets = dayBuckets(stamps, 7, now);
  assert.equal(buckets.length, 7);
  assert.equal(buckets[6], 2);   // last bucket = today
  assert.equal(buckets[5], 1);   // yesterday
  assert.equal(buckets.reduce((a, b) => a + b, 0), 3);
});
