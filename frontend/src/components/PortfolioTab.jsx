import { useCallback, useEffect, useState } from 'react';
import { del, get, post } from '../api';
import { big, num } from '../format';

const TIER_COLORS = { S: '#2ebd85', A: '#3b82f6', B: '#f0b90b', C: '#f97316', D: '#f6465d' };

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
  const currencies = [...new Set(rows.map((r) => r.currency).filter(Boolean))];

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
              <div className="dcf-label">Market value</div>
              <div className="dcf-big">{big(totals.market_value)}</div>
            </div>
            <div>
              <div className="dcf-label">Unrealized P&L</div>
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
                    <th>Ticker</th><th>Shares</th><th>Price</th><th>Cost</th>
                    <th>Value</th><th>Weight</th><th>P&L</th><th>Score</th><th>Note</th><th />
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
                      <td>
                        {r.score !== null && r.score !== undefined ? (
                          <span
                            className="tier-chip"
                            style={{ background: TIER_COLORS[r.tier] ?? 'var(--border)' }}
                            title={`scored ${r.score_as_of}`}
                          >
                            {r.score}
                          </span>
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
              Scores come from the last time you ran the Scorecard or Screener on that ticker —
              they are not refreshed here. Click a ticker to open it.
              {currencies.length > 1 && (
                <>
                  {' '}
                  <span className="down">
                    Holdings span {currencies.join(', ')} — totals add face values without FX
                    conversion, so the aggregate is indicative only.
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
