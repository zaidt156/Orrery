import { memo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { normalizeMarkdown } from "../lib/markdownFormat.js";
import { copyText } from "../lib/clipboard.js";

function CodeBlock({ className, children }) {
  const [copied, setCopied] = useState(false);
  const lang = (/language-([a-z0-9+#.-]+)/i.exec(className || "") || [])[1] || "code";
  const copy = async () => {
    const ok = await copyText(String(children).replace(/\n$/, ""));
    setCopied(ok);
    if (ok) setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="codeblock">
      <div className="codeblock-bar">
        <span className="cb-lang">{lang}</span>
        <button className={`cb-copy${copied ? " flash" : ""}`} onClick={copy}>{copied ? "✓ Copied" : "Copy"}</button>
      </div>
      <pre><code className={className}>{children}</code></pre>
    </div>
  );
}

// memo: a completed message's Markdown is re-parsed only when its text changes, not on every
// token of the streaming reply — a big speedup in long conversations.
function Markdown({ children, plain }) {
  // plain = render exactly what was typed (user prompts): never auto-fence natural language
  const normalized = plain ? String(children ?? "") : normalizeMarkdown(children);
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={{
        pre: ({ children }) => <>{children}</>,
        code({ className, children, ...props }) {
          const text = String(children ?? "");
          const block = /language-/.test(className || "") || text.includes("\n");
          if (!block) return <code className="inline-code" {...props}>{children}</code>;
          return <CodeBlock className={className}>{children}</CodeBlock>;
        },
        a: ({ children, ...props }) => <a target="_blank" rel="noreferrer" {...props}>{children}</a>,
      }}
    >
      {normalized}
    </ReactMarkdown>
  );
}

export default memo(Markdown);
