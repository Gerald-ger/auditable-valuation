/**
 * Nothing to show: absent, or a number that is not one.
 *
 * One predicate rather than four copies of the same condition, because four
 * guards that were meant to agree and did not is exactly what went wrong here —
 * `NaN` is neither `null` nor `undefined`, so it passed every one of them and
 * came out the far side as locale-dependent text.
 *
 * `Number(v)` rather than `v`, so a numeric string still formats. The explicit
 * null/undefined arm rather than `Number.isFinite` alone, because `Number(null)`
 * is `0` — written the short way this would render a missing value as a real
 * zero, which is the one distinction this whole file exists to preserve.
 */
const missing = (v) => v === null || v === undefined || !Number.isFinite(Number(v));

export function num(v, digits = 2) {
  if (missing(v)) return '—';
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function big(v) {
  if (missing(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (abs >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  return num(v);
}

export function pct(v, digits = 1) {
  if (missing(v)) return '—';
  return (v * 100).toFixed(digits) + '%';
}

/** Shared 0-100 score banding, so the Models and Scorecard tabs never disagree. */
export function scoreColor(s) {
  // `NaN` fails every `>=` below, so without this arm a score that could not be
  // computed fell through to `--down` and rendered as one that scored terribly.
  if (missing(s)) return 'var(--muted)';
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
