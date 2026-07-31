import { useEffect, useState } from 'react';
import { get, post } from '../api';
import { num, big, pct } from '../format';

function RatioCard({ title, rows }) {
  return (
    <div className="panel ratio-card">
      <div className="panel-title">{title}</div>
      <table>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <td>{label}</td>
              <td className="val">{value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function ModelsTab({ ticker }) {
  const [analysis, setAnalysis] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  // DCF assumption overrides (percent units in the UI)
  const [growth, setGrowth] = useState('');
  const [termGrowth, setTermGrowth] = useState('2.5');
  const [wacc, setWacc] = useState('');
  const [dcf, setDcf] = useState(null);
  const [dcfBusy, setDcfBusy] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setDcf(null);
    get(`/stock/${ticker}/analysis`)
      .then((a) => {
        setAnalysis(a);
        setDcf(a.dcf);
        if (a.dcf?.assumptions) {
          setGrowth((a.dcf.assumptions.growth_rate_year1 * 100).toFixed(1));
          setWacc((a.dcf.assumptions.wacc_used * 100).toFixed(1));
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker]);

  async function recalc() {
    setDcfBusy(true);
    try {
      const res = await post(`/stock/${ticker}/dcf`, {
        growth_rate: growth === '' ? null : Number(growth) / 100,
        terminal_growth: Number(termGrowth) / 100,
        wacc_override: wacc === '' ? null : Number(wacc) / 100,
      });
      setDcf(res);
    } catch (e) {
      setDcf({ error: e.message });
    } finally {
      setDcfBusy(false);
    }
  }

  if (!ticker) return <div className="empty-state">Enter a ticker above to run the models.</div>;
  if (loading) return <div className="empty-state loading">Pulling financial reports and running models…</div>;
  if (error) return <div className="error-banner">{error}</div>;
  if (!analysis) return null;

  const { company, ratios, revenue_trend } = analysis;
  const maxRev = Math.max(...revenue_trend.map((r) => r.revenue), 1);

  return (
    <div className="models-grid">
      <div className="panel company-header">
        <div className="panel-title">{company.longName}</div>
        <div className="company-meta">
          {company.sector} · {company.industry} · Mkt cap {big(company.marketCap)}{' '}
          {company.currency}
          {company.targetMeanPrice && (
            <>
              {' '}· Analyst target {num(company.targetMeanPrice)} (
              {company.numberOfAnalystOpinions} analysts, {company.recommendationKey})
            </>
          )}
        </div>
      </div>

      <div className="panel dcf-panel">
        <div className="panel-title">DCF valuation (5-year FCFF)</div>
        <div className="dcf-controls">
          <label>
            Growth yr-1 %
            <input value={growth} onChange={(e) => setGrowth(e.target.value)} />
          </label>
          <label>
            Terminal growth %
            <input value={termGrowth} onChange={(e) => setTermGrowth(e.target.value)} />
          </label>
          <label>
            WACC %
            <input value={wacc} onChange={(e) => setWacc(e.target.value)} />
          </label>
          <button className="primary" onClick={recalc} disabled={dcfBusy}>
            {dcfBusy ? 'Calculating…' : 'Recalculate'}
          </button>
        </div>
        {dcf?.error ? (
          <div className="ai-offline-note">{dcf.error}</div>
        ) : (
          dcf && (
            <>
              <div className="dcf-result">
                <div>
                  <span className="dcf-label">Fair value / share</span>
                  <span className="dcf-big">{num(dcf.fair_value_per_share)}</span>
                </div>
                <div>
                  <span className="dcf-label">Current price</span>
                  <span className="dcf-big">{num(dcf.current_price)}</span>
                </div>
                <div>
                  <span className="dcf-label">Upside</span>
                  <span
                    className={`dcf-big ${dcf.upside_pct >= 0 ? 'up' : 'down'}`}
                  >
                    {dcf.upside_pct > 0 ? '+' : ''}
                    {num(dcf.upside_pct, 1)}%
                  </span>
                </div>
                <div>
                  <span className="dcf-label">Enterprise value</span>
                  <span className="dcf-big">{big(dcf.enterprise_value)}</span>
                </div>
              </div>
              <div className="sens-title">
                Sensitivity — fair value across WACC (rows) × terminal growth (columns)
              </div>
              <table className="sens-table">
                <thead>
                  <tr>
                    <th>WACC \ g</th>
                    {dcf.sensitivity.terminal_growth_cols.map((g) => (
                      <th key={g}>{(g * 100).toFixed(2)}%</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dcf.sensitivity.rows.map((row) => (
                    <tr key={row.wacc}>
                      <td>{(row.wacc * 100).toFixed(2)}%</td>
                      {row.values.map((v, i) => (
                        <td
                          key={i}
                          className={
                            v === null ? '' : v >= dcf.current_price ? 'cell-up' : 'cell-down'
                          }
                        >
                          {v === null ? '—' : num(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )
        )}
      </div>

      <div className="ratio-grid">
        <RatioCard
          title="Profitability"
          rows={[
            ['Gross margin', pct(ratios.profitability.gross_margin)],
            ['Operating margin', pct(ratios.profitability.operating_margin)],
            ['Net margin', pct(ratios.profitability.net_margin)],
            ['ROE', pct(ratios.profitability.roe)],
            ['ROA', pct(ratios.profitability.roa)],
          ]}
        />
        <RatioCard
          title="Valuation multiples"
          rows={[
            ['P/E (trailing)', num(ratios.market.pe_trailing, 1)],
            ['P/E (forward)', num(ratios.market.pe_forward, 1)],
            ['P/B', num(ratios.market.price_to_book, 1)],
            ['EV/EBITDA', num(ratios.market.ev_to_ebitda, 1)],
            ['EV/Revenue', num(ratios.market.ev_to_revenue, 1)],
            ['PEG', num(ratios.market.peg_ratio, 2)],
            ['Dividend yield', pct(ratios.market.dividend_yield)],
          ]}
        />
        <RatioCard
          title="Liquidity & solvency"
          rows={[
            ['Current ratio', num(ratios.liquidity.current_ratio, 2)],
            ['Quick ratio', num(ratios.liquidity.quick_ratio, 2)],
            ['Debt / equity', num(ratios.solvency.debt_to_equity, 2)],
            ['Interest coverage', num(ratios.solvency.interest_coverage, 1)],
            ['Net debt', big(ratios.solvency.net_debt)],
          ]}
        />
        <RatioCard
          title="DuPont ROE decomposition"
          rows={[
            ['Net margin', pct(ratios.dupont.net_margin)],
            ['× Asset turnover', num(ratios.dupont.asset_turnover, 2)],
            ['× Equity multiplier', num(ratios.dupont.equity_multiplier, 2)],
            ['= ROE (composed)', pct(ratios.dupont.roe_composed)],
            ['Revenue growth', pct(ratios.growth.revenue_growth)],
            ['Earnings growth', pct(ratios.growth.earnings_growth)],
          ]}
        />
      </div>

      <div className="panel">
        <div className="panel-title">Revenue trend (annual reports)</div>
        <div className="rev-bars">
          {revenue_trend.map((r) => (
            <div key={r.period} className="rev-row">
              <span className="rev-period">{r.period}</span>
              <div className="rev-bar" style={{ width: `${(r.revenue / maxRev) * 100}%` }} />
              <span className="rev-val">{big(r.revenue)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
