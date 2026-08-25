// The context sizes a chat can be set to, for one model.
//
// The list a user sees has to end at the model's real maximum, because every size shown here is a
// size the backend will accept and then clamp — and a clamp is invisible. Offering 1M for a 200K
// model doesn't fail, it just quietly hands back 200K.
//
// The models Orrery reaches now span from 32K to Llama 4 Scout's 10M, which is what the fixed tier
// list below is for: standard steps up to the maximum, then the maximum itself, so the jump from
// the last tier to "max" is never more than one step.

const TIERS = [32768, 65536, 131072, 262144, 524288, 1000000, 2000000, 4000000];

export const DEFAULT_CONTEXT = 131072;

/** A short human label: "128K", "1M", "1.05M", "10M". */
export function fmtTokens(n) {
  const value = Number(n) || 0;
  if (value < 1000000) return `${Math.round(value / 1024)}K`;
  // Two decimals, trailing zeros trimmed — so 1,048,576 reads "1.05M" rather than being rounded up
  // to "1.1M", which would name a window the model doesn't have.
  return `${(value / 1000000).toFixed(2).replace(/\.?0+$/, "")}M`;
}

/** `[value, label]` pairs for the size selector, ending at the model's maximum. */
export function contextOptionsFor(maxCtx) {
  const max = Number(maxCtx) > 0 ? Number(maxCtx) : DEFAULT_CONTEXT;
  const opts = TIERS.filter((t) => t < max).map((t) => [String(t), `context: ${fmtTokens(t)}`]);
  opts.push([String(max), `context: ${fmtTokens(max)} (max)`]);
  return opts;
}

/** A model's real window from the loaded /api/models list. */
export function modelCtx(list, id) {
  return Number((list || []).find((m) => m.id === id)?.context_window) || DEFAULT_CONTEXT;
}
