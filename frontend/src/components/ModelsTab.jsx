import { useEffect, useMemo, useState } from 'react';
import { get, post } from '../api';
import { num, big, pct, scoreColor } from '../format';

/**
 * A ratio row can carry a third element: the scoring-engine metric key.
 *
 * Raw ratios answer "what is it" but not "is that good", which is the question
 * a reader actually has. Rather than invent a second set of thresholds, each row
 * borrows the 0-100 score the scorecard already computed from its calibrated
 * anchor curves — so the two tabs can never disagree about the same number.
 * Rows with no key, or whose metric the company's sector profile drops (EV/EBITDA
 * for a bank), simply show no bar.
 */
function RatioCard({ title, rows, scores }) {
  return (
    <div className="panel ratio-card">
      <div className="panel-title">{title}</div>
      <table>
        <tbody>
          {rows.map(([label, value, metric]) => {
            const score = metric ? scores[metric] : undefined;
            return (
              <tr key={label}>
                <td>{label}</td>
                <td className="val">{value}</td>
                <td className="quality">
                  {score === undefined ? (
                    <span className="quality-na" title="Not scored for this company type" />
                  ) : (
                    <span className="quality-track" title={`Quality score ${score}/100`}>
                      <span
                        className="quality-fill"
                        style={{ width: `${score}%`, background: scoreColor(score) }}
                      />
                    </span>
                  )}
                </td>
                <td className="quality-num" style={{ color: scoreColor(score) }}>
                  {score === undefined ? '' : score}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Revenue: level as a line, growth as diverging bars.
 *
 * The old chart drew bars scaled to the maximum. Because a mature company's
 * revenue barely moves year to year, every bar came out nearly the same length —
 * AAPL's four years spanned 92.1%-100% of the width. Truncating the bar axis
 * would have made the difference visible by overstating it, so instead the level
 * moves to a line (where a non-zero baseline is legitimate) and the change gets
 * its own zero-centred bars, which is where the real spread lives: XOM reads
 * -16.0%, +1.4%, -4.5% — a decline the old chart hid completely.
 */
function RevenueTrend({ trend }) {
  if (!trend.length) return <div className="chart-note">No revenue history available.</div>;

  const values = trend.map((r) => r.revenue);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  // a little headroom so the stroke is not clipped; kept small so the shape of a
  // flat series is still legible
  const lo = min - span * 0.18;
  const hi = max + span * 0.18;
  const W = 100;
  const H = 34;
  const x = (i) => (trend.length === 1 ? W / 2 : (i / (trend.length - 1)) * W);
  const y = (v) => H - ((v - lo) / (hi - lo)) * H;
  const line = trend.map((r, i) => `${x(i).toFixed(2)},${y(r.revenue).toFixed(2)}`).join(' ');
  const area = `0,${H} ${line} ${W},${H}`;

  const growth = trend.map((r, i) =>
    i === 0 || !trend[i - 1].revenue ? null : r.revenue / trend[i - 1].revenue - 1,
  );
  const maxAbs = Math.max(...growth.map((g) => Math.abs(g ?? 0)), 0.01);

  return (
    <div className="rev-trend">
      <div className="rev-level">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="rev-spark">
          <polygon points={area} fill="rgba(59,130,246,0.14)" />
          <polyline
            points={line}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
        {/* pinned to the actual plotted heights — a fixed top/bottom pair would
            label the padded bounds, not the data */}
        <span className="rev-tag" style={{ top: `${(y(max) / H) * 100}%` }}>{big(max)}</span>
        <span className="rev-tag" style={{ top: `${(y(min) / H) * 100}%` }}>{big(min)}</span>
      </div>

      <table className="rev-table">
        <tbody>
          {trend.map((r, i) => {
            const g = growth[i];
            const half = g === null ? 0 : (Math.abs(g) / maxAbs) * 50;
            return (
              <tr key={r.period}>
                <td className="rev-period">{r.period.slice(0, 4)}</td>
                <td className="rev-amount">{big(r.revenue)}</td>
                <td className="rev-track">
                  <span className="rev-zero" />
                  {g !== null && (
                    <span
                      className={`rev-delta-bar ${g >= 0 ? 'pos' : 'neg'}`}
                      style={g >= 0 ? { left: '50%', width: `${half}%` } : { right: '50%', width: `${half}%` }}
                    />
                  )}
                </td>
                <td className={`rev-delta ${g === null ? '' : g >= 0 ? 'up' : 'down'}`}>
                  {g === null ? '—' : `${g >= 0 ? '+' : ''}${(g * 100).toFixed(1)}%`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="chart-note">
        Line: revenue level (axis starts near the range, not zero — read its shape, not its
        height). Bars: year-on-year change, centred on zero.
      </div>
    </div>
  );
}

/**
 * Makes the valuation auditable at a glance: which inputs the model actually
 * used, and the two checks that say whether the answer can be trusted.
 *
 * Terminal share > 75% means the number is driven by the perpetuity assumption
 * rather than the explicit forecast. The implied exit multiple says what the
 * terminal value assumes about the multiple the market will pay in year 10 —
 * far below today's multiple means the DCF is baking in compression, which is a
 * modelling stance you should agree with rather than inherit silently.
 */
function DcfAudit({ dcf }) {
  const a = dcf.assumptions;
  const d = dcf.diagnostics;
  const termPct = d.terminal_value_share === null ? null : d.terminal_value_share * 100;
  const exitVsNow =
    d.implied_exit_ev_ebitda && d.current_ev_ebitda
      ? d.implied_exit_ev_ebitda / d.current_ev_ebitda - 1
      : null;

  return (
    <div className="dcf-audit">
      <div className="dcf-audit-row">
        <span className="dcf-label">Inputs used</span>
        <span>
          beta <b>{num(a.beta, 2)}</b>
          <span className={`src-tag ${a.beta_source}`}>{a.beta_source.replace('_', ' ')}</span>
          {a.beta_source !== 'reported' && a.beta_reported !== null && (
            <span className="muted-note"> (reported {num(a.beta_reported, 2)} — not credible)</span>
          )}
          {' · '}WACC <b>{pct(a.wacc_used)}</b>
          {' · '}risk-free <b>{pct(a.risk_free_rate)}</b>
          {' · '}credit spread <b>{pct(a.credit_spread)}</b>
          {a.interest_coverage !== null && (
            <span className="muted-note"> (coverage {num(a.interest_coverage, 1)}×)</span>
          )}
          {' · '}tax <b>{pct(a.tax_rate)}</b>
          {' · '}FCF <b>{big(a.base_fcf)}</b>
          <span className="muted-note">
            {' '}
            ({a.fcf_source === 'cash_flow_statement' ? a.fcf_period : 'info — period unverified'})
          </span>
          {' · '}forecast <b>{a.stage1_years}+{a.stage2_years}y</b>
        </span>
      </div>

      <div className="dcf-audit-row">
        <span className="dcf-label">Trust checks</span>
        <span>
          <span className={d.terminal_value_high ? 'warn-chip' : 'ok-chip'}>
            terminal value {termPct === null ? '—' : `${termPct.toFixed(0)}%`} of EV
          </span>
          {d.terminal_value_high && (
            <span className="muted-note">
              {' '}
              above 75% — the perpetuity assumption, not the forecast, is driving this
            </span>
          )}
          {d.implied_exit_ev_ebitda !== null && (
            <>
              {' '}
              <span className="ok-chip">
                implied exit {num(d.implied_exit_ev_ebitda, 1)}× EV/EBITDA
              </span>
              {d.current_ev_ebitda !== null && (
                <span className="muted-note">
                  {' '}
                  vs {num(d.current_ev_ebitda, 1)}× today
                  {exitVsNow !== null &&
                    ` — assumes ${exitVsNow < 0 ? 'compression' : 'expansion'} of ${Math.abs(
                      exitVsNow * 100,
                    ).toFixed(0)}%`}
                </span>
              )}
            </>
          )}
        </span>
      </div>
    </div>
  );
}

export default function ModelsTab({ ticker }) {
  const [analysis, setAnalysis] = useState(null);
  const [card, setCard] = useState(null);
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
    setCard(null);
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
    // the quality bars are an enhancement — a failure here must not blank the tab
    get(`/score/${ticker}`)
      .then(setCard)
      .catch(() => setCard(null));
  }, [ticker]);

  /** metric key -> 0-100, flattened across pillars (including excluded ones:
   *  a metric's own score is still valid even when its pillar was dropped). */
  const scores = useMemo(() => {
    const out = {};
    for (const pillar of Object.values(card?.pillars ?? {})) {
      for (const [key, m] of Object.entries(pillar.metrics)) out[key] = m.score;
    }
    return out;
  }, [card]);

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
        <div className="panel-title">
          DCF valuation — two-stage FCFF
          {dcf?.assumptions && (
            <span className="title-note">
              {dcf.assumptions.stage1_years} explicit years + {dcf.assumptions.stage2_years}-year
              fade to terminal
            </span>
          )}
        </div>
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
                  {/* null >= 0 is true in JS — an unavailable upside must stay
                      neutral, not render green */}
                  <span
                    className={`dcf-big ${dcf.upside_pct == null ? '' : dcf.upside_pct >= 0 ? 'up' : 'down'}`}
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
              <DcfAudit dcf={dcf} />
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

      <div className="ratio-legend">
        Bars show each ratio&rsquo;s 0&ndash;100 quality score from the scorecard&rsquo;s calibrated
        ranges for this company type
        {card?.classification && <> ({card.classification.replaceAll('_', ' ')})</>}. A blank bar
        means the metric is not scored for this type.
      </div>

      <div className="ratio-grid">
        <RatioCard
          title="Profitability"
          scores={scores}
          rows={[
            ['Gross margin', pct(ratios.profitability.gross_margin), 'gross_margin'],
            ['Operating margin', pct(ratios.profitability.operating_margin), 'operating_margin'],
            ['Net margin', pct(ratios.profitability.net_margin)],
            ['ROE', pct(ratios.profitability.roe), 'roe'],
            ['ROA', pct(ratios.profitability.roa), 'roa'],
          ]}
        />
        <RatioCard
          title="Valuation multiples"
          scores={scores}
          rows={[
            ['P/E (trailing)', num(ratios.market.pe_trailing, 1)],
            ['P/E (forward)', num(ratios.market.pe_forward, 1), 'earnings_yield_fwd'],
            ['P/B', num(ratios.market.price_to_book, 1), 'p_b'],
            ['EV/EBITDA', num(ratios.market.ev_to_ebitda, 1), 'ev_ebitda'],
            ['EV/Revenue', num(ratios.market.ev_to_revenue, 1), 'ev_sales'],
            ['PEG', num(ratios.market.peg_ratio, 2)],
            ['Dividend yield', pct(ratios.market.dividend_yield), 'dividend_yield'],
          ]}
        />
        <RatioCard
          title="Liquidity & solvency"
          scores={scores}
          rows={[
            ['Current ratio', num(ratios.liquidity.current_ratio, 2), 'current_ratio'],
            ['Quick ratio', num(ratios.liquidity.quick_ratio, 2)],
            ['Debt / equity', num(ratios.solvency.debt_to_equity, 2), 'debt_equity'],
            ['Interest coverage', num(ratios.solvency.interest_coverage, 1), 'interest_coverage'],
            ['Net debt', big(ratios.solvency.net_debt)],
          ]}
        />
        <RatioCard
          title="DuPont ROE decomposition"
          scores={scores}
          rows={[
            ['Net margin', pct(ratios.dupont.net_margin)],
            ['× Asset turnover', num(ratios.dupont.asset_turnover, 2)],
            ['× Equity multiplier', num(ratios.dupont.equity_multiplier, 2)],
            ['= ROE (composed)', pct(ratios.dupont.roe_composed), 'roe'],
            ['Revenue growth', pct(ratios.growth.revenue_growth), 'revenue_growth'],
            ['Earnings growth', pct(ratios.growth.earnings_growth), 'earnings_growth'],
          ]}
        />
      </div>

      <div className="panel">
        <div className="panel-title">Revenue trend (annual reports)</div>
        <RevenueTrend trend={revenue_trend} />
      </div>
    </div>
  );
}
