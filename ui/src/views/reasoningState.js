export function createReasoningSnapshot() {
  return { thinking: "", trace: [], outer: null, summary: null, sources: null };
}

export function applyReasoningEvent(snapshot, event) {
  const next = { ...snapshot };

  if (event.reasoning_delta != null) {
    next.thinking = (next.thinking || "") + String(event.reasoning_delta);
  }
  if (event.reasoning_step) {
    next.trace = [...(next.trace || []), event.reasoning_step];
  } else if (event.reasoning_event) {
    // Compatibility events can carry both shapes. Prefer the canonical step so it is saved once.
    next.trace = [...(next.trace || []), event.reasoning_event];
  }
  if (event.reasoning_outer) next.outer = event.reasoning_outer;
  if (event.reasoning_summary) next.summary = event.reasoning_summary;
  if (event.sources) next.sources = event.sources;

  return next;
}

export function appendRawThinking(message, text) {
  return {
    ...message,
    thinking: (message.thinking || "") + String(text ?? ""),
  };
}

export function hasReasoning(snapshot) {
  return Boolean(
    snapshot?.thinking
    || snapshot?.trace?.length
    || snapshot?.outer
    || snapshot?.summary
    || snapshot?.sources?.length
  );
}

export function splitInlineThinking(content) {
  if (!content || content.toLowerCase().indexOf("<think") === -1) {
    return { thinking: "", body: content };
  }
  const closed = /^([\s\S]*?)<think>([\s\S]*?)<\/think>([\s\S]*)$/i.exec(content);
  if (closed) {
    return { thinking: closed[2], body: (closed[1] + closed[3]).trim() };
  }
  const open = /^([\s\S]*?)<think>([\s\S]*)$/i.exec(content);
  if (open) {
    return { thinking: open[2], body: open[1].trim() };
  }
  return { thinking: "", body: content };
}
