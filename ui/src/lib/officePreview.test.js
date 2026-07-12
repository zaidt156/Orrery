import assert from "node:assert/strict";
import test from "node:test";

import { describeOfficePreviewStatus, previewNotice } from "./officePreview.js";

test("available LibreOffice status describes faithful local PDF previews", () => {
  assert.deepEqual(
    describeOfficePreviewStatus({
      available: true,
      engine: "libreoffice",
      officePreview: "pdf",
      message: "Faithful Office previews are available.",
    }),
    {
      state: "ready",
      title: "Faithful Office previews are ready",
      message: "Faithful Office previews are available.",
      detail: "PowerPoint, Word, and Excel files are converted to PDF locally for accurate layout and images.",
    },
  );
});

test("missing LibreOffice status explains the safe HTML fallback", () => {
  assert.deepEqual(
    describeOfficePreviewStatus({
      available: false,
      engine: "libreoffice",
      officePreview: "html",
      message: "LibreOffice is not installed; Office files use the HTML fallback.",
    }),
    {
      state: "fallback",
      title: "Basic Office previews are active",
      message: "LibreOffice is not installed; Office files use the HTML fallback.",
      detail: "Install LibreOffice on this computer for previews that preserve slide, document, and spreadsheet layout.",
    },
  );
});

test("malformed status responses stay conservative", () => {
  assert.equal(describeOfficePreviewStatus(null).state, "fallback");
  assert.match(describeOfficePreviewStatus({ available: false }).message, /HTML fallback/);
});

test("generated Office previews expose renderer-specific notices", () => {
  assert.deepEqual(previewNotice({ renderer: "libreoffice" }), {
    state: "ready",
    label: "Faithful Office preview",
  });
  assert.deepEqual(
    previewNotice({
      renderer: "html-fallback",
      hint: "LibreOffice is unavailable or conversion failed; showing the HTML fallback.",
    }),
    {
      state: "fallback",
      label: "Basic Office preview",
      hint: "LibreOffice is unavailable or conversion failed; showing the HTML fallback.",
    },
  );
  assert.equal(previewNotice({ renderer: "native" }), null);
});
