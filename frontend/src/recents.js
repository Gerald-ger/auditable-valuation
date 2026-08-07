// Recently viewed tickers.
//
// localStorage rather than the database: recents are a property of this browser,
// not of the portfolio, and they must survive a backend restart without a
// migration. Every access is guarded because private-browsing modes throw on
// localStorage rather than returning null, and a header convenience must never
// be able to take the page down.

const KEY = 'recent-tickers';
const MAX = 8;

export function readRecents() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((t) => typeof t === 'string') : [];
  } catch {
    return [];
  }
}

export function pushRecent(ticker) {
  const next = [ticker, ...readRecents().filter((t) => t !== ticker)].slice(0, MAX);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch { /* private mode — recents are a convenience, not a requirement */ }
  return next;
}
