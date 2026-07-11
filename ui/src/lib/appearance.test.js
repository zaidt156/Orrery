import assert from "node:assert/strict";
import test from "node:test";

import {
  applyAppearance,
  loadAppearance,
  normalizeColorTheme,
  normalizeInterface,
  saveColorTheme,
  saveInterface,
} from "./appearance.js";

function memoryStorage(seed = {}) {
  const values = new Map(Object.entries(seed));
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    snapshot: () => Object.fromEntries(values),
  };
}

test("appearance defaults are conservative and invalid values cannot reach the DOM", () => {
  assert.equal(normalizeInterface("unknown"), "classic");
  assert.equal(normalizeColorTheme("laser-rainbow"), "simple");

  const storage = memoryStorage({ "orrery-interface": "broken", "orrery-color-theme": "nope" });
  assert.deepEqual(loadAppearance(storage), { interfaceMode: "classic", colorTheme: "simple" });
});

test("legacy orrery-theme migrates once without losing the selected palette", () => {
  const storage = memoryStorage({ "orrery-theme": "futuristic" });

  assert.deepEqual(loadAppearance(storage), { interfaceMode: "classic", colorTheme: "futuristic" });
  assert.deepEqual(storage.snapshot(), { "orrery-color-theme": "futuristic" });
});

test("changing interface never changes the saved color theme", () => {
  const storage = memoryStorage({
    "orrery-interface": "classic",
    "orrery-color-theme": "winter",
  });

  const next = saveInterface("concept", storage);

  assert.deepEqual(next, { interfaceMode: "concept", colorTheme: "winter" });
  assert.deepEqual(storage.snapshot(), {
    "orrery-interface": "concept",
    "orrery-color-theme": "winter",
  });
});

test("changing color theme never changes the saved interface", () => {
  const storage = memoryStorage({
    "orrery-interface": "concept",
    "orrery-color-theme": "simple",
  });

  const next = saveColorTheme("observatory", storage);

  assert.deepEqual(next, { interfaceMode: "concept", colorTheme: "observatory" });
  assert.deepEqual(storage.snapshot(), {
    "orrery-interface": "concept",
    "orrery-color-theme": "observatory",
  });
});

test("applyAppearance writes two explicit and independent root attributes", () => {
  const root = { dataset: {} };

  applyAppearance({ interfaceMode: "concept", colorTheme: "summer" }, root);

  assert.deepEqual(root.dataset, { interface: "concept", colorTheme: "summer" });
});
