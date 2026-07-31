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
