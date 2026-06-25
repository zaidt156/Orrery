// Pure content helpers for Chat: format detection and pulling renderable bits out of replies.
import { FileDown, FileSpreadsheet, FileText } from "lucide-react";

export const EXPORT_FORMATS = [
  { id: "pdf", label: "PDF", Icon: FileText, patterns: [/\bpdf\b|\.pdf\b/i, /\breport\b/i] },
  { id: "docx", label: "Word", Icon: FileDown, patterns: [/\b(word|docx?|document)\b|\.docx?\b/i] },
  { id: "xlsx", label: "Excel", Icon: FileSpreadsheet, patterns: [/\b(excel|xlsx?|spreadsheet|workbook|sheet)\b|\.xlsx?\b/i] },
  { id: "pptx", label: "PowerPoint", Icon: FileDown, patterns: [/\b(powerpoint|pptx?|presentation|slide\s*deck|slides?)\b|\.pptx?\b/i] },
  { id: "csv", label: "CSV", Icon: FileSpreadsheet, patterns: [/\bcsv\b|\.csv\b/i] },
  { id: "md", label: "Markdown", Icon: FileText, patterns: [/\bmarkdown\b|\.md\b/i] },
  { id: "txt", label: "Text", Icon: FileText, patterns: [/\b(?:plain\s+text|text file|txt)\b|\.txt\b/i] },
  { id: "html", label: "HTML", Icon: FileText, patterns: [/\bhtml\b|web\s?page|\.html?\b/i] },
  { id: "json", label: "JSON", Icon: FileText, patterns: [/\bjson\b|\.json\b/i] },
];

export function requestedFileFormats(text) {
  if (!text) return [];
  return EXPORT_FORMATS.filter(({ patterns }) => patterns.some((pattern) => pattern.test(text)));
}

// nearest user message before index i (the prompt the assistant reply answered)
export function precedingUserText(messages, i) {
  for (let j = i - 1; j >= 0; j -= 1) {
    if (messages[j]?.role === "user") return messages[j].content || "";
  }
  return "";
}

// pull renderable HTML out of a reply: a ```html fenced block, or a full HTML document
export function extractHtml(content) {
  if (!content) return null;
  if (/<svg[\s>]/i.test(content)) return null; // SVG is rendered as an image, not HTML
  const fence = /```html\s*\n([\s\S]*?)```/i.exec(content);
  if (fence && fence[1].trim()) return fence[1].trim();
  if (/<!doctype html|<html[\s>]/i.test(content)) return content;
  return null;
}

// hide the structured ```orrery-doc spec from chat — only the model's one-line summary shows.
// Cut from the fence onward so it stays hidden while it's still streaming in too.
export function stripDocSpec(content) {
  if (!content) return content;
  const idx = content.search(/```orrery-doc/i);
  if (idx < 0) return content;
  return content.slice(0, idx).replace(/\n{3,}/g, "\n\n").trim();
}

// if the user's phrasing didn't name a format but the reply carries a spec, pick a sensible default
export function specFormats(content) {
  if (!content || !/```orrery-doc/i.test(content)) return [];
  const want = /"slides"\s*:/.test(content) ? "pptx" : /"sheets"\s*:/.test(content) ? "xlsx" : "pdf";
  return EXPORT_FORMATS.filter((f) => f.id === want);
}

// pull <svg>…</svg> images out of a reply so we render them instead of dumping the markup as code
export function extractSvgs(content) {
  if (!content || !/<svg[\s>]/i.test(content)) return { svgs: [], cleaned: content };
  const svgs = content.match(/<svg[\s\S]*?<\/svg>/gi) || [];
  if (!svgs.length) return { svgs: [], cleaned: content };
  const cleaned = content
    .replace(/```[a-z]*\s*\n?\s*<svg[\s\S]*?<\/svg>\s*```/gi, "") // fenced SVG block
    .replace(/<svg[\s\S]*?<\/svg>/gi, "") // any remaining raw SVG
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  return { svgs, cleaned };
}
