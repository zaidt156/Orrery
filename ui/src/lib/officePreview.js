const READY_DETAIL = "PowerPoint, Word, and Excel files are converted to PDF locally for accurate layout and images.";
const FALLBACK_DETAIL = "Install LibreOffice on this computer for previews that preserve slide, document, and spreadsheet layout.";

export function describeOfficePreviewStatus(status) {
  if (status?.available && status.officePreview === "pdf") {
    return {
      state: "ready",
      title: "Faithful Office previews are ready",
      message: status.message || "Faithful Office previews are available.",
      detail: READY_DETAIL,
    };
  }
  return {
    state: "fallback",
    title: "Basic Office previews are active",
    message: status?.message || "LibreOffice is unavailable; Office files use the HTML fallback.",
    detail: FALLBACK_DETAIL,
  };
}

export function previewNotice(preview) {
  if (preview?.renderer === "libreoffice") {
    return { state: "ready", label: "Faithful Office preview" };
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
