const DIRECT_IMAGE_REQUEST = /^(?:(?:can|could|would|will)\s+you\s+|please\s+)?(?:create|draw|make|generate|design|render|produce)\s+(?:me\s+)?(?:an?\s+|the\s+)?(?:image|illustration|diagram|poster|icon|logo|visual|infographic)\b/i;
const DESIRE_IMAGE_REQUEST = /^i\s+(?:want|need|would\s+like)\s+(?:you\s+to\s+)?(?:(?:create|draw|make|generate|design|render|produce)\s+)?(?:me\s+)?(?:an?\s+|the\s+)?(?:image|illustration|diagram|poster|icon|logo|visual|infographic)\b/i;
const SHOW_IMAGE_REQUEST = /^show\s+me\s+(?:an?\s+|the\s+)?(?:image|illustration|diagram|poster|icon|logo|visual|infographic)\b/i;

export function isCodeImagePrompt(value) {
  const text = String(value || "").trim();
  return /^\/image\b/i.test(text)
    || DIRECT_IMAGE_REQUEST.test(text)
    || DESIRE_IMAGE_REQUEST.test(text)
    || SHOW_IMAGE_REQUEST.test(text);
}
