let clientMessageSequence = 0;


export function createClientMessage(fields) {
  clientMessageSequence += 1;
  return { ...fields, _clientKey: `local-message-${clientMessageSequence}` };
}


export function messageKey(message, index) {
  return message?.id || message?._clientKey || `loaded-message-${index}`;
}


export function ensureStreamingAssistant(messages) {
  const next = [...messages];
  const last = next[next.length - 1];
  if (!last || last.role !== "assistant" || !last.streaming) {
    next.push(createClientMessage({ role: "assistant", content: "", streaming: true }));
  }
  return next;
}


export function appendDeltaToThread(messages, delta) {
  const next = ensureStreamingAssistant(messages);
  const last = next[next.length - 1];
  next[next.length - 1] = { ...last, content: (last.content || "") + delta };
  return next;
}


export function messageRowPropsEqual(previous, next) {
  return previous.message === next.message
    && previous.index === next.index
    && previous.isLast === next.isLast
    && previous.sending === next.sending
    && previous.copied === next.copied
    && previous.activeId === next.activeId
    && previous.activeTitle === next.activeTitle
    && previous.precedingPrompt === next.precedingPrompt
    && previous.lastPrompt === next.lastPrompt
    && previous.actions === next.actions;
}
