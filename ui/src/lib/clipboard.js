// Clipboard that actually works in the desktop webview. Qt WebEngine disables JS clipboard access
// entirely (both navigator.clipboard AND execCommand), so the desktop build copies natively through
// the Python bridge; browsers/Electron use the standard APIs.
export async function copyText(text) {
  const value = String(text ?? "");
  try {
    const bridge = window.pywebview?.api?.copy_text;
    if (bridge) {
      const r = await bridge(value);
      if (r?.ok) return true;
    }
  } catch { /* fall through to the web APIs */ }
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}
