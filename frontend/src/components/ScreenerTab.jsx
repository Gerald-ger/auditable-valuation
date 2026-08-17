import { useState } from 'react';
import { post } from '../api';
import { PILLARS, scoreColor, TIER_COLORS } from '../format';

/**
 * Rank many companies with the same deterministic engine that scores one.
 *
 * The scoring engine could already produce a 0-100 number per company, but
 * there was no way to point it at a list — so you had to know the answer
 * (which ticker to type) before asking the question.
 *
 * Ranking is grouped by classification and never crosses one. Two composites
 * from different profiles are not the same measurement — different metric sets,
 * different pillar weights, different anchor curves for some shared metrics —
 * so one sorted list asserted a comparison the engine never computed. See the
 * docstring on `score_batch` in main.py for the measurement that settled it.
 */
export default function ScreenerTab({ onPick }) {
  const [input, setInput] = useState('AAPL, MSFT, GOOGL, NVDA, JPM, XOM, 0700.HK');
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function run() {
    const tickers = input
      .split(/[\s,]+/)
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);
    if (!tickers.length) return;
    setBusy(true);
    setError(null);
    setData(null);
    try {
      setData(await post('/score/batch', { tickers }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="panel">
        <div className="panel-title">Screener: score and rank a list</div>
        <textarea
          className="screener-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Tickers separated by commas or spaces, e.g. AAPL, MSFT, 0700.HK"
          rows={3}
        />
        <div className="screener-actions">
          <button className="primary" onClick={run} disabled={busy}>
            {busy ? 'Scoring…' : 'Score all'}
          </button>
          <span className="chart-note">
            Max 50 tickers. Each is fetched, scored and stored to history. First run on a
            cold cache takes a few seconds per name.
          </span>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}
      {busy && <div className="empty-state loading">Fetching fundamentals and scoring…</div>}

      {data && (
        <div className="panel">
          <div className="panel-title">
            Ranking: within company type only
            <span className="chart-note">
              {data.ranked} ranked in {data.groups.length}{' '}
              {data.groups.length === 1 ? 'group' : 'groups'}
              {data.excluded_low_coverage > 0 &&
                ` · ${data.excluded_low_coverage} below 60% coverage (listed, not ranked)`}
              {data.failed.length > 0 && ` · ${data.failed.length} failed`}
            </span>
          </div>

          <div className="chart-note screener-why">
            Scores are <strong>not compared across company types</strong>. Each profile
            scores a different metric set, weights the pillars differently, and uses
            different anchor curves for some shared metrics, so a bank's 70 and a
            pre-profit growth company's 74 are outputs of two different formulas, not two
            readings on one scale. Compare within a group; across groups, compare pillars.
          </div>

          {data.groups.map((g) => (
            <div key={g.classification} className="screener-group">
              <div className="screener-group-head">
                {g.classification.replaceAll('_', ' ')}
                <span className="chart-note">
                  {g.comparable
                    ? `${g.ranked} comparable`
                    : 'only one company of this type: listed, not ranked'}
                </span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table className="comps-table screener-table">
                  <thead>
                    <tr>
                      <th>#</th><th>Ticker</th><th>Tier</th><th>Score</th>
                      {PILLARS.map((p) => (
                        <th key={p}>{p.slice(0, 3).toUpperCase()}</th>
                      ))}
                      <th>Conf</th><th>Cov</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.results.map((r) => (
                      <tr
                        key={r.ticker}
                        className={r.rankable ? '' : 'row-unrankable'}
                        onClick={() => onPick?.(r.ticker)}
                        title="Open in the Scorecard tab"
                      >
                        <td>{g.comparable && r.rank_in_group ? r.rank_in_group : '—'}</td>
                        <td className="screener-ticker">{r.ticker}</td>
                        <td>
                          <span
                            className="tier-chip"
                            style={{ background: TIER_COLORS[r.tier] ?? 'var(--border)' }}
                          >
                            {r.tier ?? '—'}
                          </span>
                        </td>
                        <td style={{ color: scoreColor(r.composite_score), fontWeight: 700 }}>
                          {r.composite_score ?? '—'}
                        </td>
                        {PILLARS.map((p) => {
                          const pillar = r.pillars[p];
                          return (
                            <td
                              key={p}
                              style={{ color: scoreColor(pillar?.score) }}
                              className={pillar?.insufficient ? 'pillar-excluded-cell' : ''}
                              title={pillar?.insufficient ? 'excluded from the composite' : ''}
                            >
                              {pillar?.score ?? '—'}
                              {pillar?.insufficient && '*'}
                            </td>
                          );
                        })}
                        <td>{r.confidence}</td>
                        <td>{r.coverage_pct}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}

          <div className="chart-note">
            * pillar excluded from its composite (under 40% of metrics available). Rows below
            60% coverage are not ranked: per the scoring design, a thin card must not take a
            place in a ranking it cannot support. Click a row to open it in the Scorecard tab.
          </div>
          {data.failed.length > 0 && (
            <div className="chart-note">
              Failed: {data.failed.map((f) => `${f.ticker} (${f.error})`).join(' · ')}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
