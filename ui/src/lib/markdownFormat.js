const FENCE_RE = /^\s*(```|~~~)/;

const LANGUAGE_HINTS = [
  ["python", [/^\s*(async\s+)?def\s+\w+\s*\(/, /^\s*class\s+\w+[:(]/, /^\s*(from|import)\s+[\w.]+/, /^\s*if\s+__name__\s*==/]],
  ["javascript", [/^\s*(const|let|var)\s+\w+\s*=/, /^\s*(export\s+)?(async\s+)?function\s+\w+\s*\(/, /=>\s*[{(]?/, /^\s*(import|export)\s+.+from\s+['"]/]],
  ["typescript", [/^\s*(interface|type)\s+\w+/, /:\s*(string|number|boolean|unknown|Record<)/, /^\s*(public|private|protected)\s+\w+/]],
  ["jsx", [/<[A-Z][\w.]*[\s>]/, /<\/[A-Z][\w.]*>/]],
  ["html", [/^\s*<!doctype/i, /^\s*<\/?[a-z][\w:-]*(\s|>|\/>)/i]],
  ["css", [/^\s*[.#]?[-\w]+\s*\{/, /^\s*--[-\w]+\s*:/, /^\s*@(media|keyframes|font-face)/]],
  ["json", [/^\s*[{[]\s*$/, /^\s*"[^"]+"\s*:/, /^\s*[\]},]\s*$/]],
  ["sql", [/^\s*(select\s+[\s\S]+\bfrom\b|insert\s+into\b|update\s+\w+\s+set\b|delete\s+from\b|create\s+(table|view|index|database|schema)\b|alter\s+table\b|drop\s+(table|view|index|database)\b)/i, /\b(from|join|where|group by|order by)\b/i]],
  ["bash", [/^\s*(npm|pip|python|git|docker|curl|cd|mkdir|cp|mv|rm)\s+/, /^\s*(export|source)\s+\w+/, /^\s*#!\/(usr\/bin\/env\s+)?(ba|z|fi)?sh/]],
  ["powershell", [/^\s*(Get|Set|New|Remove|Start|Stop|Select)-[A-Z]\w+/, /^\s*\$[\w:]+\s*=/, /^\s*Write-Host\b/]],
  ["yaml", [/^\s*[-\w]+\s*:\s*$/, /^\s*-\s+\w+:\s*/, /^\s{2,}[-\w]+\s*:/]],
  ["xml", [/^\s*<\?xml/, /^\s*<\/?[A-Z_a-z][\w:.-]*(\s|>|\/>)/]],
  ["java", [/^\s*(public|private|protected)\s+(class|interface|enum)\s+\w+/, /^\s*System\.out\.print/, /^\s*@Override/]],
  ["csharp", [/^\s*using\s+[\w.]+;/, /^\s*namespace\s+[\w.]+/, /^\s*(public|private|protected|internal)\s+(class|record|interface)\s+\w+/]],
  ["cpp", [/^\s*#include\s*<[^>]+>/, /^\s*std::/, /^\s*(int|void|auto)\s+main\s*\(/]],
  ["go", [/^\s*package\s+\w+/, /^\s*func\s+\w+\s*\(/, /^\s*import\s+\(/]],
  ["rust", [/^\s*fn\s+\w+\s*\(/, /^\s*let\s+mut\s+/, /^\s*use\s+[\w:]+;/]],
  ["php", [/^\s*<\?php/, /^\s*\$\w+\s*=/, /^\s*function\s+\w+\s*\(/]],
  ["ruby", [/^\s*def\s+\w+/, /^\s*class\s+\w+/, /^\s*puts\s+/]],
  ["swift", [/^\s*(import\s+Swift|func\s+\w+\s*\(|let\s+\w+\s*:)/, /^\s*(struct|class|enum)\s+\w+\s*[:{]/]],
  ["kotlin", [/^\s*fun\s+\w+\s*\(/, /^\s*(data\s+)?class\s+\w+/, /^\s*val\s+\w+\s*:/]],
  ["dart", [/^\s*void\s+main\s*\(/, /^\s*(final|var)\s+\w+\s*=/, /^\s*class\s+\w+\s*\{/]],
  ["dockerfile", [/^\s*FROM\s+[\w./:-]+/i, /^\s*(RUN|COPY|ADD|CMD|ENTRYPOINT)\s+/i]],
  ["toml", [/^\s*\[[\w.-]+]\s*$/, /^\s*[\w.-]+\s*=\s*["\d]/]],
];

const STRONG_CODE_RE = [
  /^\s*(async\s+)?def\s+\w+\s*\(/,
  /^\s*(const|let|var)\s+\w+\s*=/,
  /^\s*(export\s+)?(async\s+)?function\s+\w+\s*\(/,
  /^\s*(class|interface|type|struct|enum)\s+\w+/,
  /^\s*(if|for|while|switch|try|catch|except|else if|elif)\b.*[:{]\s*$/,
  /^\s*(return|yield|await|throw|raise)\b/,
  /^\s*(SELECT\s+[\s\S]+\bFROM\b|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b|DELETE\s+FROM\b|CREATE\s+(TABLE|VIEW|INDEX|DATABASE|SCHEMA|FUNCTION|PROCEDURE|TRIGGER)\b|ALTER\s+(TABLE|VIEW|DATABASE)\b|DROP\s+(TABLE|VIEW|INDEX|DATABASE|SCHEMA)\b)/i,
  /^\s*<\/?[A-Za-z][\w:-]*(\s|>|\/>)/,
  /^\s*[.#]?[-\w]+\s*\{\s*$/,
  /^\s*#include\s*<[^>]+>/,
  /^\s*package\s+\w+/,
  /^\s*func\s+\w+\s*\(/,
  /^\s*fn\s+\w+\s*\(/,
  /^\s*using\s+[\w.]+;/,
  /^\s*FROM\s+[\w./:-]+/i,
];

const WEAK_CODE_RE = [
  /[{}();]\s*$/,
  /^\s*[}\])],?\s*$/,
  /^\s*[\w.$[\]'"-]+\s*=\s*.+[,;]?\s*$/,
  /^\s*"[^"]+"\s*:\s*.+[,;]?\s*$/,
  /^\s*'[^']+'\s*:\s*.+[,;]?\s*$/,
  /^\s*([a-z_][\w.-]*|[A-Z_][A-Z0-9_]*)\s*:\s*(["'\w[{]|$)/,
  /^\s{2,}\S/,
];

function isListOrQuote(line) {
  return /^\s*(>|[-*+]\s|\d+\.\s)/.test(line);
}

function isLikelyCodeLine(line) {
  if (!line.trim() || isListOrQuote(line)) return false;
  return STRONG_CODE_RE.some((re) => re.test(line)) || WEAK_CODE_RE.some((re) => re.test(line));
}

function isStrongCodeLine(line) {
  return STRONG_CODE_RE.some((re) => re.test(line));
}

function shouldFenceBlock(lines) {
  const codeLines = lines.filter((line) => line.trim() && isLikelyCodeLine(line));
  if (codeLines.length >= 2) return true;
  if (codeLines.length === 1 && isStrongCodeLine(codeLines[0])) return true;
  return false;
}

function guessLanguage(lines) {
  const text = lines.join("\n");
  let best = ["text", 0];
  for (const [lang, tests] of LANGUAGE_HINTS) {
    const score = tests.reduce((n, re) => n + (re.test(text) ? 1 : 0), 0);
    if (score > best[1]) best = [lang, score];
  }
  return best[0];
}

function flushCodeBlock(out, pending) {
  if (!pending.length) return;
  if (shouldFenceBlock(pending)) {
    const trimmed = [...pending];
    while (trimmed.length && !trimmed[0].trim()) trimmed.shift();
    while (trimmed.length && !trimmed[trimmed.length - 1].trim()) trimmed.pop();
    out.push(`\`\`\`${guessLanguage(trimmed)}`);
    out.push(...trimmed);
    out.push("```");
  } else {
    out.push(...pending);
  }
  pending.length = 0;
}

export function normalizeMarkdown(raw) {
  const text = String(raw || "").replace(/\r\n/g, "\n");
  const lines = text.split("\n");
  const out = [];
  const pending = [];
  let fenced = false;

  for (const line of lines) {
    if (FENCE_RE.test(line)) {
      flushCodeBlock(out, pending);
      fenced = !fenced;
      out.push(line);
      continue;
    }
    if (fenced) {
      out.push(line);
      continue;
    }
    if (isLikelyCodeLine(line) || (pending.length && !line.trim())) {
      pending.push(line);
      continue;
    }
    flushCodeBlock(out, pending);
    out.push(line);
  }
  flushCodeBlock(out, pending);
  return out.join("\n");
}
