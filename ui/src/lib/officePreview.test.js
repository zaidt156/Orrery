import assert from "node:assert/strict";
import test from "node:test";

import {
  describeOfficePreviewStatus,
  officePreviewInstallAction,
  previewFrameSandbox,
  previewNotice,
} from "./officePreview.js";

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
      detail: "Install LibreOffice, or build the sandbox image, for previews that preserve slide, document, and spreadsheet layout.",
    },
  );
});

test("malformed status responses stay conservative", () => {
  assert.equal(describeOfficePreviewStatus(null).state, "fallback");
  assert.match(describeOfficePreviewStatus({ available: false }).message, /HTML fallback/);
});

test("missing LibreOffice exposes an install action only to admins with a package manager", () => {
  assert.deepEqual(officePreviewInstallAction({ available: false, canInstall: true }, true), {
    label: "Install & enable",
    enabled: true,
  });
  assert.equal(officePreviewInstallAction({ available: false, canInstall: false }, true), null);
  assert.equal(officePreviewInstallAction({ available: false, canInstall: true }, false), null);
  assert.equal(officePreviewInstallAction({ available: true, canInstall: false }, true), null);
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
  assert.deepEqual(previewNotice({ renderer: "libreoffice-partial", hint: "Partial preview." }), {
    state: "fallback",
    label: "Partial Office preview",
    hint: "Partial preview.",
  });
});

test("preview iframes deny capabilities by default and only opt in for interactive apps", () => {
  assert.equal(previewFrameSandbox(), "");
  assert.equal(previewFrameSandbox(false), "");
  assert.equal(previewFrameSandbox(true), "allow-scripts allow-forms allow-modals");
  assert.doesNotMatch(previewFrameSandbox(true), /allow-same-origin|allow-popups/);
});

test("the sandbox engine reads as working previews, not a fallback", () => {
  const described = describeOfficePreviewStatus({
    available: true,
    engine: "sandbox",
    officePreview: "html",
    message: "Office previews render in the offline sandbox, including OpenDocument.",
  });

  assert.equal(described.state, "sandboxed");
  assert.match(described.title, /ready|working|active/i);
  assert.doesNotMatch(described.title, /basic/i);
});

test("LibreOffice is offered as an upgrade when the sandbox already renders", () => {
  const action = officePreviewInstallAction(
    { available: true, engine: "sandbox", canInstall: true }, true);

  assert.ok(action, "an upgrade should still be offered");
  assert.doesNotMatch(action.label, /install & enable/i);
});

test("only the host engine reads as degraded", () => {
  const described = describeOfficePreviewStatus({
    available: false, engine: "host", officePreview: "html",
  });

  assert.equal(described.state, "fallback");
});
