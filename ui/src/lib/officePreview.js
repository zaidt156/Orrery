const READY_DETAIL = "PowerPoint, Word, and Excel files are converted to PDF locally for accurate layout and images.";
const SANDBOX_DETAIL = "Word, Excel, PowerPoint, and OpenDocument files are rendered inside the offline sandbox, so nothing is parsed by the app itself. Installing LibreOffice adds page-faithful layout for Office formats.";
const FALLBACK_DETAIL = "Install LibreOffice, or build the sandbox image, for previews that preserve slide, document, and spreadsheet layout.";

export function previewFrameSandbox(interactive = false) {
  return interactive ? "allow-scripts allow-forms allow-modals" : "";
}

export function describeOfficePreviewStatus(status) {
  if (status?.available && status.officePreview === "pdf") {
    return {
      state: "ready",
      title: "Faithful Office previews are ready",
      message: status.message || "Faithful Office previews are available.",
      detail: READY_DETAIL,
    };
  }
  // The sandbox is a working renderer, not a degraded one: it covers every supported format and is
  // the only thing that reads OpenDocument. Calling it a fallback told users to fix what worked.
  if (status?.available && status.engine === "sandbox") {
    return {
      state: "sandboxed",
      title: "Office previews are ready",
      message: status.message || "Office previews render in the offline sandbox.",
      detail: SANDBOX_DETAIL,
    };
  }
  return {
    state: "fallback",
    title: "Basic Office previews are active",
    message: status?.message || "LibreOffice is unavailable; Office files use the HTML fallback.",
    detail: FALLBACK_DETAIL,
  };
}

export function officePreviewInstallAction(status, canManage) {
  if (!status?.canInstall || !canManage) return null;
  // Where the sandbox already renders, LibreOffice buys page-faithful layout rather than fixing
  // something broken, and the button should not imply otherwise.
  if (status.available) {
    return status.engine === "sandbox"
      ? { label: "Add page-faithful layout", enabled: true }
      : null;
  }
  return { label: "Install & enable", enabled: true };
}

export function previewNotice(preview) {
  if (preview?.renderer === "libreoffice") {
    return { state: "ready", label: "Faithful Office preview" };
  }
  if (preview?.renderer === "libreoffice-partial") {
    return {
      state: "fallback",
      label: "Partial Office preview",
      hint: preview.hint || "The safe preview limit was reached.",
    };
  }
  if (preview?.renderer === "html-fallback") {
    return {
      state: "fallback",
      label: "Basic Office preview",
      hint: preview.hint || "LibreOffice is unavailable; showing the HTML fallback.",
    };
  }
  return null;
}
