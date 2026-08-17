export function num(v, digits = 2) {
  if (v === null || v === undefined) return '—';
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function big(v) {
  if (v === null || v === undefined) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (abs >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  return num(v);
}

export function pct(v, digits = 1) {
  if (v === null || v === undefined) return '—';
  return (v * 100).toFixed(digits) + '%';
}

/** Shared 0-100 score banding, so the Models and Scorecard tabs never disagree. */
export function scoreColor(s) {
  if (s === null || s === undefined) return 'var(--muted)';
  if (s >= 65) return 'var(--up)';
  if (s >= 50) return 'var(--gold)';
  return 'var(--down)';
}

/**
 * Tier badge colours, shared by the Scorecard, Screener and Portfolio tabs.
 * Hex rather than CSS vars: S/B/D match --up/--gold/--down, but A and C have no
 * palette entry, and adding two vars just to make this uniform is not worth it.
 */
export const TIER_COLORS = { S: '#2ebd85', A: '#3b82f6', B: '#f0b90b', C: '#f97316', D: '#f6465d' };

/** Pillar order as the scoring engine emits it — mirrors store.PILLARS. */
export const PILLARS = ['valuation', 'quality', 'health', 'growth', 'momentum'];
