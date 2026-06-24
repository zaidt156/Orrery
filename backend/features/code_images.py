from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET

from backend.providers import ai

MAX_SVG_BYTES = 200_000
_SVG_BLOCK = re.compile(r"<svg\b[\s\S]*?</svg>", re.IGNORECASE)
_INTERNAL_URL = re.compile(r"^url\(\s*#[A-Za-z_][A-Za-z0-9_.:-]*\s*\)$")

_ALLOWED_TAGS = {
    "svg", "g", "rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
    "text", "tspan", "defs", "linearGradient", "radialGradient", "stop", "clipPath",
}
_ALLOWED_ATTRS = {
    "id", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "d", "points", "fill", "stroke", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "opacity", "transform",
    "font-size", "font-family", "font-weight", "font-style", "text-anchor", "dominant-baseline",
    "offset", "stop-color", "stop-opacity", "clip-path", "fill-opacity", "stroke-opacity",
}
_DANGEROUS_VALUE = re.compile(
    r"(?:javascript:|data:|https?:|file:|vbscript:|expression\s*\(|@import)",
    re.IGNORECASE,
)

SVG_SYSTEM_PROMPT = """\
Create a polished vector image as SVG code from the user's request.
Return only one complete <svg>...</svg> document, with a 1200 by 800 viewBox.
Do not wrap the SVG in Markdown fences and do not include any explanation.
Use only these elements: svg, g, rect, circle, ellipse, line, polyline, polygon,
path, text, tspan, defs, linearGradient, radialGradient, stop, clipPath.
Use only explicit element attributes. Do not use script, style, foreignObject, image,
use, animation, links, external resources, event handlers, CSS, embedded data,
XML declarations, DOCTYPE, entities, or namespace extensions.
Prefer simple shapes, paths, gradients, and short readable labels over unsupported effects.
Use explicit fills/strokes and accessible contrast. The result must be self-contained
and under 180 KB.
"""


class UnsafeSvgError(ValueError):
    """Raised when generated SVG cannot be rendered inside Orrery's strict profile."""


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1] if "}" in value else value


def _validate_value(name: str, value: str) -> None:
    if len(value) > 80_000:
        raise UnsafeSvgError("Generated SVG contains an oversized attribute.")
    if _DANGEROUS_VALUE.search(value):
        raise UnsafeSvgError("Generated SVG attempted to reference external content.")
    if "url(" in value.lower() and not _INTERNAL_URL.fullmatch(value.strip()):
        raise UnsafeSvgError("Generated SVG contains an unsafe URL reference.")
    if name == "transform" and len(value) > 2_000:
        raise UnsafeSvgError("Generated SVG contains an oversized transform.")


def sanitize_svg(raw: str) -> str:
    """Return a strict, self-contained SVG or reject it.

    The model writes declarative vector markup only. Orrery never executes model-written
    Python, JavaScript, shell, HTML, browser automation, or filesystem code.
    """
    if not isinstance(raw, str):
        raise UnsafeSvgError("The model did not return SVG text.")
    if re.search(r"<!DOCTYPE|<!ENTITY|<\?xml", raw, re.IGNORECASE):
        raise UnsafeSvgError("Generated SVG contains forbidden XML features.")
    match = _SVG_BLOCK.search(raw)
    if not match:
        raise UnsafeSvgError("The model did not return a complete SVG image.")
    svg = match.group(0).strip()
    if len(svg.encode("utf-8")) > MAX_SVG_BYTES:
        raise UnsafeSvgError("Generated SVG is too large.")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise UnsafeSvgError("Generated SVG is not valid XML.") from exc
    if _local_name(root.tag) != "svg":
        raise UnsafeSvgError("Generated image must have an SVG root.")

    for node in root.iter():
        tag = _local_name(node.tag)
        if tag not in _ALLOWED_TAGS:
            raise UnsafeSvgError(f"Generated SVG uses unsupported element: {tag}.")
        node.tag = tag
        cleaned: dict[str, str] = {}
        for raw_name, raw_value in node.attrib.items():
            name = _local_name(raw_name)
            if name.lower().startswith("on") or name not in _ALLOWED_ATTRS:
                raise UnsafeSvgError(f"Generated SVG uses unsupported attribute: {name}.")
            value = str(raw_value).strip()
            _validate_value(name, value)
            cleaned[name] = value
        node.attrib.clear()
        node.attrib.update(cleaned)
        if node.text and len(node.text) > 8_000:
            raise UnsafeSvgError("Generated SVG contains oversized text.")
        if node.tail and len(node.tail) > 8_000:
            raise UnsafeSvgError("Generated SVG contains oversized text.")

    root.set("viewBox", root.get("viewBox") or "0 0 1200 800")
    root.set("width", "1200")
    root.set("height", "800")
    root.set("xmlns", "http://www.w3.org/2000/svg")
    safe = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    if len(safe.encode("utf-8")) > MAX_SVG_BYTES:
        raise UnsafeSvgError("Generated SVG is too large after validation.")
    return safe


def image_prompt(text: str) -> str:
    cleaned = re.sub(r"^\s*/image\b\s*:?\s*", "", text or "", flags=re.IGNORECASE).strip()
    return cleaned or "Create a clean abstract illustration."



def _wrap_label(value: str, max_chars: int = 28, max_lines: int = 3) -> list[str]:
    words = re.sub(r"\s+", " ", value or "").strip().split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:max_chars]
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines or ["Generated image"]


def fallback_svg(prompt: str) -> str:
    """Build a safe static SVG when a model cannot satisfy the strict SVG profile."""
    digest = hashlib.sha256((prompt or "orrery").encode("utf-8", errors="ignore")).hexdigest()
    accent = f"#{digest[:6]}"
    accent2 = f"#{digest[6:12]}"
    lines = _wrap_label(prompt)
    text_nodes = []
    start_y = 360 - (len(lines) - 1) * 32
    for index, line in enumerate(lines):
        text_nodes.append(
            f'<text x="600" y="{start_y + index * 64}" fill="#E8ECF8" font-size="42" '
            f'font-family="Arial" font-weight="700" text-anchor="middle">{html.escape(line)}</text>'
        )
    raw = f'''<svg viewBox="0 0 1200 800" width="1200" height="800">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0B1020"/>
      <stop offset="1" stop-color="#18213F"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="45%" r="55%">
      <stop offset="0" stop-color="{accent}" stop-opacity="0.92"/>
      <stop offset="1" stop-color="{accent2}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="1200" height="800" fill="url(#bg)"/>
  <circle cx="600" cy="380" r="310" fill="url(#glow)" opacity="0.58"/>
  <ellipse cx="600" cy="400" rx="410" ry="150" fill="none" stroke="#9DB9F0" stroke-width="5" opacity="0.72" transform="rotate(-12 600 400)"/>
  <ellipse cx="600" cy="400" rx="310" ry="96" fill="none" stroke="#F2B14E" stroke-width="4" opacity="0.76" transform="rotate(18 600 400)"/>
  <circle cx="870" cy="305" r="18" fill="#F2B14E"/>
  <circle cx="315" cy="510" r="10" fill="#9DB9F0"/>
  {''.join(text_nodes)}
  <text x="600" y="585" fill="#8A94B8" font-size="20" font-family="Arial" text-anchor="middle">Safe SVG fallback</text>
</svg>'''
    return sanitize_svg(raw)


async def generate_svg(
    model: str,
    prompt: str,
    system_prompt: str | None = None,
    effort: str | None = None,
) -> str:
    instructions = SVG_SYSTEM_PROMPT
    if system_prompt:
        instructions += f"\nUser style instructions:\n{system_prompt.strip()[:4_000]}"

    last_error: Exception | None = None
    request = image_prompt(prompt)
    for attempt in range(3):
        parts: list[str] = []
        turn = request
        if attempt:
            turn += (
                "\n\nYour previous output failed strict SVG validation. Return only a valid SVG "
                "using the exact allowed elements and attributes, with no CSS or external content."
            )
        async for delta in ai.stream_chat(
            model,
            [{"role": "user", "content": turn}],
            instructions,
            effort,
        ):
            if not isinstance(delta, ai.ReasoningDelta):
                parts.append(str(delta))
        try:
            return sanitize_svg("".join(parts))
        except UnsafeSvgError as exc:
            last_error = exc
    return fallback_svg(request or str(last_error or "Generated image"))
