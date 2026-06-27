from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

from backend.features.prompting import SVG_SYSTEM_PROMPT
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

_TEXT_ALLOWED_HINT = re.compile(
    r"\b("
    r"text|label|labels|title|caption|headline|wordmark|brand name|logo name|"
    r"write|written|typography|lettering|letters|monogram|initials|poster|"
    r"banner|sign|badge|button|chart|diagram label|ui text|include the words|"
    r"named|called"
    r")\b",
    re.IGNORECASE,
)

_TEXT_ONLY_RATIO_LIMIT = 0.45



class UnsafeSvgError(ValueError):
    """Raised when generated SVG cannot be rendered inside Orrery's strict profile."""


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1] if "}" in value else value


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _text_is_allowed(prompt: str) -> bool:
    return bool(_TEXT_ALLOWED_HINT.search(prompt or ""))


def _visible_text_from_tree(root: ET.Element) -> list[str]:
    values: list[str] = []

    for node in root.iter():
        tag = _local_name(str(node.tag))
        if tag in {"text", "tspan"}:
            text = _normalize_text(node.text or "")
            if text:
                values.append(text)

    return values


def _count_visual_nodes(root: ET.Element) -> int:
    visual_tags = {
        "rect", "circle", "ellipse", "line", "polyline", "polygon", "path",
        "linearGradient", "radialGradient", "stop", "clipPath",
    }

    count = 0
    for node in root.iter():
        tag = _local_name(str(node.tag))
        if tag in visual_tags:
            count += 1

    return count


def _validate_text_usage(root: ET.Element, prompt: str | None) -> None:
    prompt = prompt or ""
    allow_text = _text_is_allowed(prompt)
    text_values = _visible_text_from_tree(root)

    if not text_values:
        return

    if not allow_text:
        raise UnsafeSvgError(
            "Generated SVG used visible text even though the user did not explicitly request text."
        )

    combined_text = _normalize_text(" ".join(text_values))
    normalized_prompt = _normalize_text(prompt)

    if len(combined_text) >= 24 and combined_text in normalized_prompt:
        raise UnsafeSvgError("Generated SVG appears to render the user's prompt as visible text.")

    visual_node_count = _count_visual_nodes(root)
    text_length = sum(len(value) for value in text_values)
    geometry_weight = max(visual_node_count * 12, 1)
    text_ratio = text_length / (text_length + geometry_weight)

    if text_ratio > _TEXT_ONLY_RATIO_LIMIT:
        raise UnsafeSvgError("Generated SVG is too text-heavy and lacks enough visual geometry.")


def _validate_value(name: str, value: str) -> None:
    if len(value) > 80_000:
        raise UnsafeSvgError("Generated SVG contains an oversized attribute.")

    if _DANGEROUS_VALUE.search(value):
        raise UnsafeSvgError("Generated SVG attempted to reference external content.")

    if "url(" in value.lower() and not _INTERNAL_URL.fullmatch(value.strip()):
        raise UnsafeSvgError("Generated SVG contains an unsafe URL reference.")

    if name == "transform" and len(value) > 2_000:
        raise UnsafeSvgError("Generated SVG contains an oversized transform.")


def sanitize_svg(raw: str, prompt: str | None = None) -> str:
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

    if _local_name(str(root.tag)) != "svg":
        raise UnsafeSvgError("Generated image must have an SVG root.")

    for node in root.iter():
        tag = _local_name(str(node.tag))

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

    _validate_text_usage(root, prompt)

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


def fallback_svg(prompt: str) -> str:
    """Build a safe static SVG when a model cannot satisfy the strict SVG profile.

    Important: this fallback must not render the user's prompt as visible text.
    """
    digest = hashlib.sha256((prompt or "orrery").encode("utf-8", errors="ignore")).hexdigest()

    accent = f"#{digest[:6]}"
    accent2 = f"#{digest[6:12]}"

    raw = f'''<svg viewBox="0 0 1200 800" width="1200" height="800">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0B1020"/>
      <stop offset="1" stop-color="#18213F"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="44%" r="58%">
      <stop offset="0" stop-color="{accent}" stop-opacity="0.78"/>
      <stop offset="1" stop-color="{accent2}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#FFE2A0"/>
      <stop offset="0.48" stop-color="#F2B14E"/>
      <stop offset="1" stop-color="#A86B18"/>
    </linearGradient>
    <linearGradient id="ice" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#E8F4FF"/>
      <stop offset="1" stop-color="#78A9E6"/>
    </linearGradient>
  </defs>

  <rect x="0" y="0" width="1200" height="800" fill="url(#bg)"/>
  <circle cx="600" cy="380" r="330" fill="url(#glow)" opacity="0.48"/>

  <ellipse cx="600" cy="410" rx="390" ry="126" fill="none" stroke="#9DB9F0" stroke-width="5" opacity="0.58" transform="rotate(-12 600 410)"/>
  <ellipse cx="600" cy="410" rx="310" ry="92" fill="none" stroke="#F2B14E" stroke-width="4" opacity="0.72" transform="rotate(16 600 410)"/>
  <ellipse cx="600" cy="410" rx="230" ry="62" fill="none" stroke="#E8ECF8" stroke-width="2" opacity="0.48" transform="rotate(4 600 410)"/>

  <line x1="600" y1="250" x2="600" y2="520" stroke="#9DB9F0" stroke-width="6" stroke-linecap="round" opacity="0.85"/>
  <circle cx="600" cy="250" r="62" fill="url(#gold)" stroke="#FFE7B8" stroke-width="5"/>
  <circle cx="600" cy="250" r="28" fill="#FFFFFF" opacity="0.12"/>

  <ellipse cx="600" cy="535" rx="155" ry="40" fill="#07142F" stroke="#9DB9F0" stroke-width="4" opacity="0.95"/>
  <ellipse cx="600" cy="535" rx="108" ry="26" fill="none" stroke="#F2B14E" stroke-width="3" opacity="0.82"/>
  <ellipse cx="600" cy="535" rx="64" ry="14" fill="none" stroke="#E8F4FF" stroke-width="2" opacity="0.72"/>

  <line x1="390" y1="350" x2="390" y2="505" stroke="#9DB9F0" stroke-width="4" stroke-linecap="round"/>
  <circle cx="390" cy="350" r="35" fill="url(#ice)" stroke="#E8F4FF" stroke-width="4"/>

  <line x1="470" y1="285" x2="470" y2="515" stroke="#9DB9F0" stroke-width="5" stroke-linecap="round"/>
  <circle cx="470" cy="285" r="43" fill="#0A2D62" stroke="#9DB9F0" stroke-width="4"/>

  <line x1="742" y1="335" x2="742" y2="500" stroke="#9DB9F0" stroke-width="4" stroke-linecap="round"/>
  <circle cx="742" cy="335" r="31" fill="url(#ice)" stroke="#E8F4FF" stroke-width="4"/>

  <line x1="820" y1="292" x2="820" y2="515" stroke="#9DB9F0" stroke-width="5" stroke-linecap="round"/>
  <circle cx="820" cy="292" r="37" fill="url(#gold)" stroke="#FFE7B8" stroke-width="4"/>
  <ellipse cx="820" cy="292" rx="60" ry="16" fill="none" stroke="#F2B14E" stroke-width="5" transform="rotate(-18 820 292)"/>

  <circle cx="910" cy="385" r="15" fill="#F2B14E"/>
  <circle cx="303" cy="478" r="12" fill="#9DB9F0"/>
  <circle cx="860" cy="565" r="10" fill="#E8F4FF"/>
  <circle cx="333" cy="287" r="9" fill="#F2B14E"/>

  <path d="M260 282 C355 140 528 105 670 128" fill="none" stroke="#9DB9F0" stroke-width="4" stroke-linecap="round" opacity="0.64"/>
  <path d="M765 133 C920 184 1010 320 1002 475" fill="none" stroke="#F2B14E" stroke-width="4" stroke-linecap="round" opacity="0.72"/>
  <path d="M275 565 C390 705 610 728 760 650" fill="none" stroke="#9DB9F0" stroke-width="4" stroke-linecap="round" opacity="0.58"/>

  <circle cx="256" cy="284" r="18" fill="none" stroke="#E8F4FF" stroke-width="5"/>
  <circle cx="1002" cy="475" r="18" fill="none" stroke="#F2B14E" stroke-width="5"/>
  <circle cx="760" cy="650" r="14" fill="none" stroke="#9DB9F0" stroke-width="4"/>

  <line x1="510" y1="660" x2="690" y2="660" stroke="#9DB9F0" stroke-width="3" stroke-linecap="round"/>
  <circle cx="555" cy="660" r="8" fill="#F2B14E"/>
  <circle cx="645" cy="660" r="8" fill="#F2B14E"/>
  <line x1="600" y1="660" x2="600" y2="710" stroke="#9DB9F0" stroke-width="3" stroke-linecap="round"/>
  <circle cx="600" cy="710" r="10" fill="none" stroke="#E8F4FF" stroke-width="4"/>
</svg>'''

    return sanitize_svg(raw, prompt=None)


async def generate_svg(
    model: str,
    prompt: str,
    system_prompt: str | None = None,
    effort: str | None = None,
) -> str:
    instructions = SVG_SYSTEM_PROMPT

    if system_prompt:
        instructions += f"\nAdditional style instructions:\n{system_prompt.strip()[:4_000]}"

    last_error: Exception | None = None
    request = image_prompt(prompt)

    base_turn = f"""\
Design brief:
{request}

Remember:
The design brief above is not visible text.
Do not write the brief into the SVG.
Only include visible text if the brief explicitly asks for specific visible words,
a brand name, wordmark, label, title, chart label, UI text, lettering, or typography.
Return only the SVG document.
"""

    for attempt in range(3):
        parts: list[str] = []

        turn = base_turn

        if attempt:
            turn += (
                "\n\nYour previous output failed strict SVG validation."
                f"\nValidation failure: {str(last_error)[:500]}"
                "\nReturn only a valid SVG using the exact allowed elements and attributes."
                "\nDo not use CSS, comments, external content, unsupported attributes, or prompt text."
                "\nThe result must be a real vector illustration, not a text-only image."
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
            return sanitize_svg("".join(parts), prompt=request)
        except UnsafeSvgError as exc:
            last_error = exc

    return fallback_svg(request or str(last_error or "Generated image"))
