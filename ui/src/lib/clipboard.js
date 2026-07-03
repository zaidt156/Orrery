// Desktop clipboard helper. It tries every safe route Orrery supports:
// native desktop bridge, browser clipboard, legacy DOM copy, then the protected local API.
const API_BASE = import.meta.env.DEV ? "http://127.0.0.1:8765" : "";

function sessionToken() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") || sessionStorage.getItem("orrery_token") || "";
  if (token) sessionStorage.setItem("orrery_token", token);
  return token;
}

async function backendCopy(value) {
  const token = sessionToken();
  if (!token) return { ok: false, error: "No Orrery desktop session token." };
  const response = await fetch(`${API_BASE}/api/clipboard/copy`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Orrery-Token": token,
    },
    body: JSON.stringify({ text: value }),
  });
  if (response.ok) return { ok: true, method: "api" };
  let detail = `Clipboard API failed (${response.status}).`;
  try {
    const body = await response.json();
    detail = body.detail || detail;
  } catch {
    // keep status-based detail
  }
  return { ok: false, error: detail };
}

function domCopy(value) {
  const selection = document.getSelection();
  const previousRange = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
  const ta = document.createElement("textarea");
  ta.value = value;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "0";
  ta.style.left = "0";
  ta.style.width = "1px";
  ta.style.height = "1px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  ta.setSelectionRange(0, ta.value.length);
  const ok = document.execCommand("copy");
  ta.remove();
  if (selection && previousRange) {
    selection.removeAllRanges();
    selection.addRange(previousRange);
  }
  return ok;
}

export async function copyTextResult(text) {
  const value = String(text ?? "");
  const errors = [];

  try {
    const bridge = window.pywebview?.api?.copy_text;
    if (bridge) {
      const result = await bridge(value);
      if (result === true || result?.ok === true || result === undefined) {
        return { ok: true, method: "desktop" };
      }
      errors.push(result?.error || "Desktop clipboard bridge returned false.");
    }
  } catch (error) {
    errors.push(error?.message || String(error));
  }

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return { ok: true, method: "browser" };
    }
    errors.push("Browser clipboard API is unavailable.");
  } catch (error) {
    errors.push(error?.message || String(error));
  }

  try {
    if (domCopy(value)) return { ok: true, method: "dom" };
    errors.push("DOM copy fallback was rejected.");
  } catch (error) {
    errors.push(error?.message || String(error));
  }

  try {
    const result = await backendCopy(value);
    if (result.ok) return result;
    errors.push(result.error || "Backend clipboard fallback failed.");
  } catch (error) {
    errors.push(error?.message || String(error));
  }

  return { ok: false, error: errors.filter(Boolean).join(" | ") || "Clipboard copy failed." };
}

export async function copyText(text) {
  return (await copyTextResult(text)).ok;
}
