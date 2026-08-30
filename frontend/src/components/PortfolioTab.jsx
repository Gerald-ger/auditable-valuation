import { useCallback, useEffect, useState } from 'react';
import { del, get, post } from '../api';
import { big, num, TIER_COLORS } from '../format';

/**
 * Watchlist and holdings.
 *
 * A row with 0 shares is a watchlist entry; give it shares and a cost basis and
 * it becomes a position. Weights and concentration are computed over held
 * positions only — a watchlist name has no weight by definition.
 */
export default function PortfolioTab({ onPick }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ ticker: '', shares: '', cost_basis: '', note: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await get('/portfolio'));
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function save(e) {
    e.preventDefault();
    if (!form.ticker.trim()) return;
    try {
      await post('/portfolio/position', {
        ticker: form.ticker.trim().toUpperCase(),
        shares: Number(form.shares) || 0,
        cost_basis: form.cost_basis === '' ? null : Number(form.cost_basis),
        note: form.note || null,
      });
      setForm({ ticker: '', shares: '', cost_basis: '', note: '' });
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(ticker) {
    try {
      await del(`/portfolio/position/${ticker}`);
      await load();
    } catch (err) {
      setError(err.message);
    }
  }

  if (loading && !data) return <div className="empty-state loading">Pricing your positions…</div>;

  const rows = data?.rows ?? [];
  const totals = data?.totals ?? {};
  const conc = data?.concentration ?? {};
  // Only the rows that reach the totals, because the warning below is about the
  // totals. Truthy market_value is the same test main.portfolio() uses to build
  // `held`, so it excludes a watchlist row (no shares) and an unpriced one alike;
  // either would otherwise contribute a currency to a sum it is absent from. Read
  // over every row, this fired on a portfolio of five USD holdings because a
  // watched HK name was listed beneath them.
  const currencies = [
    ...new Set(rows.filter((r) => r.market_value).map((r) => r.currency).filter(Boolean)),
  ];
  // Every money figure the backend converted is in `totals.currency`; when it
  // could not price a currency it withholds the totals, leaves the rows as
  // reported, and names what it could not price. The suffix follows that: a
  // column labelled HKD when the numbers are not is worse than no label.
  const unpriced = totals.unconverted_currencies ?? [];
  const unit = totals.currency ? ` (${totals.currency})` : '';

  return (
    <div>
      <div className="panel">
        <div className="panel-title">Add or update a position</div>
        <form className="position-form" onSubmit={save}>
          <label>
            Ticker
            <input
              value={form.ticker}
              onChange={(e) => setForm({ ...form, ticker: e.target.value })}
              placeholder="AAPL"
            />
          </label>
          <label>
            Shares
            <input
              type="number"
              step="any"
              value={form.shares}
              onChange={(e) => setForm({ ...form, shares: e.target.value })}
              placeholder="0 = watch only"
            />
          </label>
          <label>
            Cost basis / share
            <input
              type="number"
              step="any"
              value={form.cost_basis}
              onChange={(e) => setForm({ ...form, cost_basis: e.target.value })}
              placeholder="optional"
            />
          </label>
          <label className="grow">
            Note
            <input
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              placeholder="optional"
            />
          </label>
          <button className="primary" type="submit">Save</button>
        </form>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {rows.length === 0 ? (
        <div className="empty-state">
          Nothing tracked yet. Add a ticker above, or use “+ Watchlist” on the Scorecard tab.
        </div>
      ) : (
        <>
          <div className="panel portfolio-totals">
            <div>
              <div className="dcf-label">Market value{unit}</div>
              <div className="dcf-big">{big(totals.market_value)}</div>
            </div>
            <div>
              <div className="dcf-label">Unrealized P&L{unit}</div>
              {/* null >= 0 is true in JS, so an unavailable total rendered
                  green. Same bug already fixed on the DCF upside chip. */}
              <div
                className={`dcf-big ${
                  totals.unrealized_pnl == null ? '' : totals.unrealized_pnl >= 0 ? 'up' : 'down'
                }`}
              >
                {totals.unrealized_pnl == null
                  ? '—'
                  : `${totals.unrealized_pnl >= 0 ? '+' : ''}${big(totals.unrealized_pnl)}`}
                {totals.unrealized_pnl_pct !== null &&
                  totals.unrealized_pnl_pct !== undefined && (
                    <span className="score-outof">
                      {totals.unrealized_pnl_pct >= 0 ? '+' : ''}
                      {totals.unrealized_pnl_pct}%
                    </span>
                  )}
              </div>
            </div>
            <div>
              <div className="dcf-label">Holdings</div>
              <div className="dcf-big">
                {totals.holdings}
                <span className="score-outof">+{totals.watchlist_only} watching</span>
              </div>
            </div>
            <div>
              <div className="dcf-label">Top weight</div>
              <div className="dcf-big">
                {conc.top_weight_pct ? `${conc.top_weight_pct}%` : '—'}
                {conc.top3_weight_pct && (
                  <span className="score-outof">top 3: {conc.top3_weight_pct}%</span>
                )}
              </div>
            </div>
            <div>
              <div className="dcf-label">Concentration (HHI)</div>
              <div className="dcf-big">{conc.hhi ?? '—'}</div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-title">Positions and watchlist</div>
            <div style={{ overflowX: 'auto' }}>
              <table className="comps-table">
                <thead>
                  <tr>
                    {/* Price and cost are per-share quotes in the holding's own
                        market and stay in its own currency; value and P&L are
                        converted, so only those two carry the unit. */}
                    <th>Ticker</th><th>Shares</th><th>Price</th><th>Cost</th>
                    <th>Value{unit}</th><th>Weight</th><th>P&L{unit}</th>
                    <th>Score</th><th>Note</th><th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.ticker} className={r.shares ? '' : 'row-watchlist'}>
                      <td className="screener-ticker" onClick={() => onPick?.(r.ticker)}>
                        {r.ticker}
                        {r.quote_error && <span className="down" title={r.quote_error}> ⚠</span>}
                      </td>
                      <td>{r.shares || '—'}</td>
                      <td>{num(r.price)}</td>
                      <td>{num(r.cost_basis)}</td>
                      <td>{r.market_value ? big(r.market_value) : '—'}</td>
                      <td>{r.weight_pct ? `${r.weight_pct.toFixed(1)}%` : '—'}</td>
                      {/* The two P&L fields have different null conditions — a
                          zero cost basis has a real gain and no percentage
                          return (see position_values in main.py). Reading the
                          percentage off the absolute one's guard threw, and
                          because the throw is inside this render the
                          ErrorBoundary took the add/edit form down with the
                          table, leaving no way to correct the position. */}
                      <td className={r.unrealized_pnl > 0 ? 'up' : r.unrealized_pnl < 0 ? 'down' : ''}>
                        {r.unrealized_pnl == null
                          ? '—'
                          : `${big(r.unrealized_pnl)}${
                              r.unrealized_pnl_pct == null
                                ? ''
                                : ` (${r.unrealized_pnl_pct >= 0 ? '+' : ''}${r.unrealized_pnl_pct.toFixed(1)}%)`
                            }`}
                      </td>
                      {/* The profile sits beside the number, not in its own
                          column, because the table already carries ten. Without
                          it these composites read as one scale: RIVN's 74 lands
                          next to AAPL's 67 and they are outputs of different
                          formulas — the comparison ScreenerTab refuses to make. */}
                      <td>
                        {r.score !== null && r.score !== undefined ? (
                          <>
                            <span
                              className="tier-chip"
                              style={{ background: TIER_COLORS[r.tier] ?? 'var(--border)' }}
                              title={`scored ${r.score_as_of}`}
                            >
                              {r.score}
                            </span>
                            {r.classification && (
                              <span className="screener-profile">
                                {r.classification.replaceAll('_', ' ')}
                              </span>
                            )}
                          </>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="screener-profile">{r.note}</td>
                      <td>
                        <button className="row-remove" onClick={() => remove(r.ticker)}>
                          ✕
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="chart-note">
              Scores come from the last time you ran the Scorecard or Screener on that ticker;
              they are not refreshed here. Click a ticker to open it.{' '}
              {/* Same wording as ScreenerTab, deliberately: two tabs must not
                  describe the same limitation differently. */}
              <strong>Scores are not comparable across company types</strong>. The profile
              beside each one names the formula that produced it, and two profiles score
              different metrics on different weights. Compare within a type; across types,
              open the scorecards and compare pillars.
              {/* This used to read "totals add face values without FX conversion,
                  so the aggregate is indicative only". It was accurate until the
                  totals were converted and is false now — and a caveat that
                  outlives the defect it describes teaches the reader to ignore
                  the next one. */}
              {unpriced.length > 0 ? (
                <>
                  {' '}
                  <span className="down">
                    No exchange rate for {unpriced.join(', ')}: the totals are withheld
                    rather than added across units, and each row is shown in its own
                    currency.
                  </span>
                </>
              ) : currencies.length > 1 && (
                <>
                  {' '}
                  <span>
                    Holdings span {currencies.join(', ')}; value, cost and P&L are
                    converted to {totals.currency} at today&rsquo;s rate. Price and cost
                    per share stay in each holding&rsquo;s own currency.
                  </span>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
