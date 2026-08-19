import { useEffect, useMemo, useState } from 'react';
import { get, post } from '../api';
import { num, big, pct, scoreColor } from '../format';
import { DISPLAY_TZ_LABEL, DISPLAY_TZ_OFFSET_S } from '../charttime';

/**
 * Epoch seconds as a wall clock in the app's display timezone.
 *
 * Reuses the chart's GMT+8 offset rather than the browser's locale, for the
 * reason `charttime.js` gives: one timeline for both markets, so a Hong Kong
 * reader sees HK times read naturally. A quote stamp shown in a different zone
 * from the chart directly above it would be worse than showing no stamp.
 */
/**
 * Where the CAPM risk-free rate came from, for the tag beside it.
 *
 * `RF_STAND_INS` drives the styling and is the distinction that matters: both
 * of these mean *no rate for this currency was used*, and they get the muted
 * treatment the other `src-tag` fallbacks get. Everything else is a real curve
 * for the currency being discounted and reads as sourced — so a new local curve
 * added here is styled correctly by default rather than mislabelled a fallback,
 * which is what an `=== 'us_treasury_10y'` test did to the CGB rate.
 */
const RF_STAND_INS = new Set(['usd_proxy', 'platform_default']);

const RF_SOURCE_LABEL = {
  us_treasury_10y: 'US 10Y',
  cgb_10y_less_spread: 'China 10Y − default spread',
  usd_proxy: 'USD proxy',
  platform_default: 'platform default',
};

function priceClock(epochSeconds) {
  if (typeof epochSeconds !== 'number') return null;
  return new Date((epochSeconds + DISPLAY_TZ_OFFSET_S) * 1000)
    .toISOString()
    .slice(11, 16);
}

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
        Line: revenue level (axis starts near the range, not zero; read its shape, not its
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
          {/* Two different statements that used to share one sentence. Before a
              measured beta existed, not using the vendor's figure always meant
              it had failed the credibility band. Now it usually means we simply
              had a better source, and calling a perfectly ordinary vendor beta
              "not credible" would be an accusation the data does not support. */}
          {a.beta_source !== 'reported' && a.beta_reported != null && (
            <span className="muted-note">
              {' '}(vendor {num(a.beta_reported, 2)}
              {a.beta_reported_credible === false && ', not credible'})
            </span>
          )}
          {/* A slope on its own cannot say whether it measured anything. XOM
              and AAPL used to print here in the same typeface — 0.2888 and
              1.1546 — while the index explains 46% of AAPL's movement and under
              3% of XOM's, and XOM's interval is wide enough to move its fair
              value from 123 to 228. Published rather than flagged: a threshold
              for "too weak" would be a constant seven fixtures cannot
              calibrate, and the reader can see 0.03 for themselves. */}
          {a.beta_r_squared != null && (
            <span
              className="muted-note"
              title={
                `The index explains ${(a.beta_r_squared * 100).toFixed(0)}% of this ` +
                `company's week-to-week movement. The range is the 95% confidence ` +
                `interval for the slope — the wider it is, the less the exact ` +
                `figure should be leaned on.`
              }
            >
              {' '}(R² {num(a.beta_r_squared, 2)}
              {a.beta_confidence_interval &&
                `, 95% ${num(a.beta_confidence_interval[0], 2)}–${num(
                  a.beta_confidence_interval[1], 2)}`}
              )
            </span>
          )}
          {/* The credibility band was written for a vendor figure that could
              not be checked. When it fires on a measured one, say so rather
              than printing the clamped value as if it were the measurement. */}
          {a.beta_regressed != null && a.beta_regressed !== a.beta && (
            <span className="muted-note">
              {' '}— regressed {num(a.beta_regressed, 4)}, held at the{' '}
              {num(a.beta, 2)} band
            </span>
          )}
          {' · '}WACC <b>{pct(a.wacc_used)}</b>
          {' · '}risk-free <b>{pct(a.risk_free_rate)}</b>
          {/* Tagged for the same reason the premium below is, and it is the
              half that used to hide: an HKD filer is still discounted at the US
              ten-year, so this tag and the market in brackets below can name two
              different countries. That disagreement is the disclosure — without
              it the two numbers look like one consistent pair. A CNY filer no
              longer disagrees: it reads China's own curve. */}
          {a.risk_free_source && (
            <span className={`src-tag ${RF_STAND_INS.has(a.risk_free_source)
              ? 'default' : 'reported'}`}>
              {RF_SOURCE_LABEL[a.risk_free_source]
                ?? a.risk_free_source.replace(/_/g, ' ')}
            </span>
          )}
          {/* The ERP was a bare 5% for every market on earth until it was
              sourced. Shown with its market because that is the surprising
              part: 0700.HK trades in Hong Kong but reports in CNY, so it is
              priced off China's premium, not Hong Kong's. */}
          {a.equity_risk_premium !== undefined && (
            <>
              {' · '}equity premium <b>{pct(a.equity_risk_premium)}</b>
              <span className={`src-tag ${a.equity_risk_premium_source?.startsWith('damodaran')
                ? 'reported' : 'default'}`}>
                {a.equity_risk_premium_source?.startsWith('damodaran')
                  ? `Damodaran ${a.equity_risk_premium_source.slice(-10)}`
                  : a.equity_risk_premium_source?.replace(/_/g, ' ')}
              </span>
              {a.equity_risk_premium_market && (
                <span className="muted-note"> ({a.equity_risk_premium_market})</span>
              )}
            </>
          )}
          {' · '}credit spread <b>{pct(a.credit_spread)}</b>
          {a.interest_coverage !== null && (
            <span className="muted-note">
              {' '}(coverage {num(a.interest_coverage, 1)}×
              {/* the period is shown because it is not always the newest one:
                  both legs are pinned to a single year, and for AAPL that is
                  2023 — yfinance stopped reporting interest after it */}
              {a.interest_coverage_period && ` in ${a.interest_coverage_period}`})
            </span>
          )}
          {' · '}tax <b>{pct(a.tax_rate)}</b>
          {' · '}FCF <b>{big(a.base_fcf)}</b>
          <span className="muted-note">
            {' '}
            ({a.fcf_source === 'cash_flow_statement' ? a.fcf_period : 'info, period unverified'})
          </span>
          {' · '}forecast <b>{a.stage1_years}+{a.stage2_years}y</b>
          {/* Only shown when the two currencies actually differ, which is the
              China-domiciled HK listings: 0700.HK reports CNY and trades HKD.
              Without conversion its upside read +30.5% against +44.5% correct. */}
          {a.fx_basis === 'converted' && (
            <span className="muted-note">
              {' '}· statements in <b>{a.reporting_currency}</b>, converted to{' '}
              <b>{a.currency}</b> at {num(a.fx_rate_used, 4)}
            </span>
          )}
          {/* The price is the denominator of the upside above and was the only
              input here carrying no provenance. The delay is the vendor's own
              figure, not an estimate — a free feed is 15 minutes behind the
              exchange and says so. Market-cap multiples are not refreshed with
              it, so the note says which figures moved and which did not. */}
          {(a.price_as_of || a.price_delayed_by_minutes) && (
            <span className="muted-note">
              {' '}· price{' '}
              {a.price_as_of && <>as of <b>{priceClock(a.price_as_of)}</b> {DISPLAY_TZ_LABEL}</>}
              {a.price_delayed_by_minutes
                ? `, feed delayed ${a.price_delayed_by_minutes} min`
                : ''}
              {' '}(multiples below are as of {a.fcf_period})
            </span>
          )}
        </span>
      </div>

      {/* 2.5% was a bare constant on screen for as long as it existed, which
          made the single most levered assumption in the model the only one with
          no visible derivation. Both ceilings are shown whether or not they
          bind: a reader cannot tell a limit was respected unless it is there. */}
      {a.terminal_growth_ceilings && (
        <div className="dcf-audit-row">
          <span className="dcf-label">Terminal growth</span>
          <span>
            <b>{pct(a.terminal_growth)}</b>
            {a.terminal_growth_source === 'user' ? (
              <span className="muted-note"> (set by you, ceilings not applied)</span>
            ) : (
              <>
                <span className="muted-note">
                  {' '}· anchor <b>{pct(a.terminal_growth_anchor)}</b>, held under
                  long-run nominal GDP{' '}
                  <b>{pct(a.terminal_growth_ceilings.nominal_gdp_growth)}</b> (nothing
                  outgrows its economy forever) and the risk-free rate{' '}
                  <b>{pct(a.terminal_growth_ceilings.risk_free_rate)}</b> (Damodaran&rsquo;s
                  cap: the ten-year is itself a market read of long-run nominal growth)
                </span>
                {a.terminal_growth_source === 'capped_at_risk_free_rate' && (
                  <>
                    {' '}
                    <span className="warn-chip">
                      cut to the risk-free rate in a low-rate regime
                    </span>
                  </>
                )}
              </>
            )}
          </span>
        </div>
      )}

      <div className="dcf-audit-row">
        <span className="dcf-label">Trust checks</span>
        <span>
          {/* A bridge leg the provider did not report is assumed zero so the
              model still runs, which makes a company look debt-free rather than
              unreported. Saying so is the whole point of the assumption. */}
          {d.net_debt_assumed_zero?.length > 0 && (
            <>
              <span className="warn-chip">
                {d.net_debt_assumed_zero.map((leg) => leg.replace('_', ' ')).join(' and ')} not
                reported, assumed zero in the equity bridge
              </span>{' '}
            </>
          )}
          {/* Fair value is in the reporting currency and the price is not, so
              an upside would be a comparison of two different units. */}
          {a.fx_basis === 'rate_unavailable' && (
            <>
              <span className="warn-chip">
                no {a.reporting_currency}/{a.currency} rate: upside withheld, fair value is
                in {a.reporting_currency}
              </span>{' '}
            </>
          )}
          <span className={d.terminal_value_high ? 'warn-chip' : 'ok-chip'}>
            terminal value {termPct === null ? '—' : `${termPct.toFixed(0)}%`} of EV
          </span>
          {d.terminal_value_high && (
            <span className="muted-note">
              {' '}
              above 75%: the perpetuity assumption, not the forecast, is driving this
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
                    ` (assumes ${exitVsNow < 0 ? 'compression' : 'expansion'} of ${Math.abs(
                      exitVsNow * 100,
                    ).toFixed(0)}%)`}
                </span>
              )}
            </>
          )}
          {/* The same check run backwards, and the more useful direction:
              "assumes compression of 70%" invites the reader to conclude the
              stock is expensive, when the exit multiple is really a statement
              about what a 2.5% perpetuity can express. Solving for the growth
              today's price already assumes turns it into a question about the
              business instead. Reference doc §1.1.4. */}
          {d.market_implied_terminal_growth !== null
            && d.market_implied_terminal_growth !== undefined && (
            <>
              {' '}
              <span className={d.market_implied_growth_high ? 'warn-chip' : 'ok-chip'}>
                today&rsquo;s price implies {pct(d.market_implied_terminal_growth)} perpetual growth
              </span>
              <span className="muted-note">
                {' '}
                {d.market_implied_growth_high
                  ? `, which is above ${pct(d.nominal_gdp_growth)} long-run nominal GDP, so the market is
                     pricing growth above the economy forever`
                  : `, which is below ${pct(d.nominal_gdp_growth)} long-run nominal GDP, so the price needs
                     nothing unusual`}
              </span>
            </>
          )}
        </span>
      </div>
    </div>
  );
}

/**
 * The base year, and the size of choosing it.
 *
 * Free cash flow enters the valuation linearly, so a base year 22% below normal
 * is a valuation 22% below normal — permanently. This shows the company's own
 * margin history, the exact operating/capital decomposition of the newest year,
 * and what the same model returns on a normalised base.
 *
 * It deliberately does not choose. Whether MSFT's capex wave ends is a forecast
 * about the world, not a fact in the accounts, and a platform that picked for
 * the reader would be hiding the largest assumption in the model behind a
 * single number.
 */
/**
 * `base_year.driver_note` in words. The six cases are resolved in
 * financial_models.base_year_context, where they are tested — which leg is
 * larger and which way each leg pushed are separate facts, and deriving the
 * second from the first in JSX is how the panel once told 0700.HK it was
 * "spending more" in the same breath as naming operating cash the larger leg.
 */
const DRIVER_NOTES = {
  both_adverse: 'Both legs moved against free cash flow here.',
  both_favourable: 'Both legs moved in free cash flow’s favour.',
  spending_more_not_earning_less:
    'Operating cash moved the other way, so this is a business spending more rather than earning less.',
  spending_less_offset_weaker_earnings:
    'Lower capital spending more than offset the weaker operating cash.',
  earning_more_despite_spending_more:
    'Capital spending rose as well, but the extra operating cash outweighed it.',
  earning_less_not_spending_more:
    'Capital spending did not add to it, so the movement is in what the business earned.',
};

/** A signed movement in percentage points — the sign is the whole message. */
function signedPp(v) {
  if (v === null || v === undefined) return '—';
  return `${v > 0 ? '+' : ''}${(v * 100).toFixed(1)}pp`;
}

// Named so the rows read as a bridge rather than a list of balance-sheet trivia.
// Order matters: claims on the business first, then assets outside it, which is
// the order the reference doc states the identity in.
// `why` takes the balance-sheet date because one row's argument depends on it:
// the securities are defensible *because* the filing already marked them, and a
// mark is a statement about a day. The other two are claims rather than marks
// and age less, but they are dated in the heading all the same.
const BRIDGE_ROWS = [
  ['minority_interest', 'Minority interest',
   () => 'a claim on the business held by someone else'],
  ['preferred', 'Preferred equity', () => 'ranks ahead of the ordinary shares'],
  ['marked_securities', 'Investment securities',
   (period) => `already carried at fair value in the ${period} filing, so no mark `
     + 'is being invented — but a mark is a statement about that day, not today'],
];

function EquityBridgePanel({ dcf }) {
  const b = dcf.diagnostics?.equity_bridge;
  if (!b) return null;
  const ccy = dcf.assumptions?.currency;
  const ps = b.per_share || {};
  const rows = BRIDGE_ROWS.filter(([key]) => ps[key]);
  const assoc = ps.associates_at_cost;

  // A bridge with nothing to add is still worth one line. The alternative is
  // silence, and silence here reads as "there was nothing to check" rather than
  // "we checked and there was nothing" — the distinction this panel exists for.
  if (!rows.length && !assoc && !b.disappeared?.length) {
    return (
      <div className="chart-note">
        Equity bridge: enterprise value less net debt. As of{' '}
        <b>{b.period}</b> this company reports no minority interest, preferred
        equity or investments held outside the operating business, so there is
        nothing further to bridge.
      </div>
    );
  }

  // The starting point, backed out rather than passed down: the headline already
  // has every row applied, so subtracting them recovers what the bridge was
  // before. Keeps one number authoritative instead of two that can drift.
  const base = dcf.fair_value_per_share - rows.reduce((t, [k]) => t + ps[k], 0);

  return (
    <>
      <div className="sens-title">
        Bridge: from enterprise value to a value per share
        {/* One date for all three rows, because `equity_bridge` is period-pinned
            by design and refuses a cross-year fallback — so they cannot come
            from different balance sheets. */}
        <span className="muted-note"> — balance-sheet terms as of {b.period}</span>
      </div>
      <table className="sens-table">
        <tbody>
          <tr>
            <td style={{ textAlign: 'left' }}>Enterprise value less net debt</td>
            <td />
            <td>{num(base)}</td>
          </tr>
          {rows.map(([key, label, why]) => (
            <tr key={key}>
              <td style={{ textAlign: 'left' }}>
                {ps[key] < 0 ? '−' : '+'} {label}
                <span className="muted-note"> — {why(b.period)}</span>
              </td>
              <td />
              <td>{ps[key] > 0 ? '+' : '−'}{num(Math.abs(ps[key]))}</td>
            </tr>
          ))}
          <tr>
            <td style={{ textAlign: 'left' }}>
              = <b>Fair value / share</b> — the headline above
            </td>
            <td />
            <td><b>{num(dcf.fair_value_per_share)}</b> {ccy}</td>
          </tr>
        </tbody>
      </table>

      {b.disappeared?.map((key) => (
        <span className="warn-chip" key={key}>
          {key.replaceAll('_', ' ')} was reported in an earlier year and is absent from{' '}
          {b.period}: read as nil rather than carried forward
        </span>
      ))}

      {assoc ? (
        <>
          <table className="sens-table">
            <tbody>
              <tr>
                <td style={{ textAlign: 'left' }}>
                  Associates and joint ventures, <b>held at cost</b>
                </td>
                <td>+{num(assoc)}</td>
                <td>
                  <b>{num(b.fair_value_including_associates)}</b> {ccy}
                </td>
              </tr>
            </tbody>
          </table>
          <div className="chart-note">
            This last line is <b>not</b> in the headline. The stakes are carried at
            what they cost, and cost is neither a market value nor a floor — a
            long-held stake is usually worth more than it cost, an impaired one
            less, and the filing does not say which. Marking them would be a
            judgement about assets we cannot see, so the figure is shown and left
            out of the number. The rows above it are different in kind: the
            securities are already carried at fair value in the filing, and the
            deductions are claims on the business that are not the shareholders&rsquo;.
          </div>
        </>
      ) : (
        <div className="chart-note">
          Enterprise value belongs to everyone with a claim on the business, so
          the deductions above remove the claims that are not the ordinary
          shareholders&rsquo;, and the additions bring in what the cash-flow forecast
          never counted. A discounted cash flow values the operating business; an
          asset parked beside it earns nothing in that forecast and has to be
          added separately or it is valued at zero.
        </div>
      )}
    </>
  );
}

function BaseYearPanel({ dcf }) {
  const b = dcf.diagnostics?.base_year;
  if (!b?.history?.length) return null;
  // A null ratio means the average margin was zero and nothing can be said
  // about representativeness — which is not the same as "it is representative",
  // so neither branch of the sentence below may run.
  const known = b.ratio_to_mean !== null && b.ratio_to_mean !== undefined;
  const off = known && Math.abs(b.ratio_to_mean - 1) > 0.05;
  const ccy = dcf.assumptions?.currency;

  return (
    <>
      <div className="sens-title">
        Base year: is {dcf.assumptions.fcf_period} representative?
      </div>
      <table className="sens-table base-year-table">
        <thead>
          <tr>
            <th>Year</th>
            <th>Operating cash / revenue</th>
            <th>Capex / revenue</th>
            <th>FCF / revenue</th>
          </tr>
        </thead>
        <tbody>
          {b.history.map((h, i) => (
            <tr key={h.period} className={i === b.history.length - 1 ? 'base-year-latest' : ''}>
              <td style={{ textAlign: 'left' }}>{h.period.slice(0, 10)}</td>
              <td>{pct(h.operating_margin_cash)}</td>
              <td>{pct(h.capex_to_revenue)}</td>
              <td><b>{pct(h.fcf_margin)}</b></td>
            </tr>
          ))}
          <tr className="base-year-mean">
            <td style={{ textAlign: 'left' }}>{b.periods}-year average</td>
            <td />
            <td />
            <td><b>{pct(b.mean_fcf_margin)}</b></td>
          </tr>
        </tbody>
      </table>

      <div className="chart-note">
        {known && (
          <>The newest year is <b>{num(b.ratio_to_mean, 2)}×</b> its own {b.periods}-year
            average margin.{' '}</>
        )}
        {known && off ? (
          <>
            Against that average, operating cash moved{' '}
            <b>{signedPp(b.operating_delta)}</b> of revenue and capital spending{' '}
            <b>{signedPp(b.capex_delta)}</b>. More capital spending lowers free
            cash flow.{' '}
            <b>
              {b.driver === 'capital_spending' ? 'Capital spending' : 'Operating cash'}
            </b>{' '}
            is the larger of the two.{' '}
            {DRIVER_NOTES[b.driver_note]}
            {' '}The two legs sum exactly to the change; nothing is assumed to
            attribute it.
          </>
        ) : (
          known && 'It is close to its own average, so this choice moves the valuation little.'
        )}
      </div>

      {b.fair_value_normalised !== null && (
        <>
          <table className="sens-table">
            <tbody>
              <tr>
                <td style={{ textAlign: 'left' }}>
                  On the reported year: <b>the headline above</b>, ticks to a filing
                </td>
                <td><b>{num(dcf.fair_value_per_share)}</b> {ccy}</td>
                <td>{dcf.upside_pct > 0 ? '+' : ''}{num(dcf.upside_pct, 1)}%</td>
              </tr>
              <tr>
                <td style={{ textAlign: 'left' }}>
                  On this company&rsquo;s {b.periods}-year average margin, at today&rsquo;s revenue
                </td>
                <td><b>{num(b.fair_value_normalised)}</b> {ccy}</td>
                <td>
                  {b.fair_value_normalised_upside_pct > 0 ? '+' : ''}
                  {num(b.fair_value_normalised_upside_pct, 1)}%
                </td>
              </tr>
            </tbody>
          </table>
          <div className="chart-note">
            We do not choose between these. Which is right depends on whether the
            movement above persists: a judgement about the future, not a figure in
            the accounts, so the platform declines to make it for you. Note the
            adjustment is not one-way: it lowers companies whose newest year ran
            <i> above</i> their own average and raises those below, which is what
            separates a correction from a nudge toward the market price.
          </div>
        </>
      )}
    </>
  );
}

export default function ModelsTab({ ticker }) {
  const [analysis, setAnalysis] = useState(null);
  const [card, setCard] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  // DCF assumption overrides (percent units in the UI)
  const [growth, setGrowth] = useState('');
  // Empty like the other two: the placeholder shows the resolved rate, so the
  // box says what the model used without claiming the reader chose it.
  const [termGrowth, setTermGrowth] = useState('');
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
        // Empty means "use the platform's policy rate", which is the anchor
        // held under the GDP and risk-free ceilings — the same convention the
        // other two inputs already use. Sending 2.5% unconditionally made every
        // recalculation look like a deliberate override and hid the ceilings.
        terminal_growth: termGrowth === '' ? null : Number(termGrowth) / 100,
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
          DCF valuation: two-stage FCFF
          {dcf?.assumptions && (
            <span className="title-note">
              {dcf.assumptions.stage1_years} explicit years + {dcf.assumptions.stage2_years}-year
              fade to terminal
            </span>
          )}
        </div>
        {/* A DCF built on `CFO - CapEx` is meaningless for some company types
            and still returns a confident-looking number: O renders a -63.0%
            upside off a base cash flow that treats a REIT's property
            acquisitions as maintenance capex, and a bank has no such quantity at
            all. The scoring engine already drops dcf_upside_pct for these
            profiles; this says so here rather than leaving the two tabs to
            disagree in silence. The model is still shown — the reader may want
            the sensitivity grid — but it is not presented as an answer. */}
        {card && card.dcf_applicable === false && (
          <div className="ai-offline-note">
            A discounted-cash-flow valuation does not apply to a{' '}
            {card.classification.replaceAll('_', ' ')}: free cash flow here is{' '}
            {card.classification === 'real_estate_reit'
              ? 'operating cash flow less capital expenditure, and for a REIT that capex is property acquisition rather than maintenance'
              : 'not a meaningful quantity for this balance sheet'}
            . The Scorecard leaves it out of the valuation pillar for the same reason. Read
            the peer multiples and the football field instead.
          </div>
        )}
        <div className="dcf-controls">
          <label>
            Growth yr-1 %
            <input value={growth} onChange={(e) => setGrowth(e.target.value)} />
          </label>
          <label>
            Terminal growth %
            <input
              value={termGrowth}
              placeholder={dcf?.assumptions
                ? (dcf.assumptions.terminal_growth * 100).toFixed(2)
                : ''}
              onChange={(e) => setTermGrowth(e.target.value)}
            />
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
              {/* Every figure on this panel is quoted in one currency, and it
                  is named — an unlabelled 628.44 under a header reading "Mkt cap
                  4.33T HKD" was in a different unit from the price beside it
                  until the conversion below existed. */}
              <div className="dcf-result">
                <div>
                  <span className="dcf-label">
                    Fair value / share {dcf.assumptions?.currency}
                  </span>
                  <span className="dcf-big">{num(dcf.fair_value_per_share)}</span>
                </div>
                <div>
                  <span className="dcf-label">
                    Current price {dcf.assumptions?.currency}
                  </span>
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
                Sensitivity: fair value across WACC (rows) × terminal growth (columns)
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

              {/* The grid above moves WACC and terminal growth — the two
                  second-order assumptions — and holds the starting growth rate
                  fixed. That rate is the first-order driver, and the Scorecard's
                  DCF bar is built from this sweep as well as the grid, so it has
                  to be visible here or that bar cannot be audited. */}
              {/* The base year anchors every projected year and the terminal
                  value, and FCF enters linearly — so a contaminated base is a
                  permanent proportional error. Reported stays the headline; the
                  alternative is shown beside it, decomposed into filed lines, so
                  the reader can judge the adjustment rather than trust it. The
                  wording stays neutral about the cause: the bridge shows whether
                  working capital or capital expenditure moved. */}
              <BaseYearPanel dcf={dcf} />

              {/* The bridge from enterprise value to a share price. It ran on one
                  of the five terms the reference doc specifies, and said so
                  nowhere — on 0700.HK the missing three are 28% of enterprise
                  value and reverse the verdict. Shown in full so the reader can
                  see both what is counted and where the platform stops. */}
              <EquityBridgePanel dcf={dcf} />

              {dcf.diagnostics.base_fcf_quality?.anomalous && (
                <>
                  <div className="sens-title">
                    Base year: cash conversion has broken from this company&rsquo;s own history
                  </div>
                  <div className="chart-note">
                    Free cash flow was{' '}
                    <b>{pct(dcf.diagnostics.base_fcf_quality.conversion)}</b> of net income in{' '}
                    {dcf.assumptions.fcf_period}, against{' '}
                    <b>{pct(dcf.diagnostics.base_fcf_quality.reference)}</b> across the other
                    filed years, a {pct(Math.abs(dcf.diagnostics.base_fcf_quality.deviation))} break.
                    The DCF above uses the <b>reported</b> figure. The bridge below shows what a
                    normal working-capital movement would give instead; if the two are close, the
                    break is not working capital and the capital-expenditure line is where to look.
                  </div>
                  {dcf.diagnostics.base_fcf_quality.bridge && (
                    <table className="sens-table">
                      <tbody>
                        {dcf.diagnostics.base_fcf_quality.bridge.map((r) => (
                          <tr key={r.label}>
                            <td style={{ textAlign: 'left' }}>{r.label}</td>
                            <td>{big(r.value)}</td>
                          </tr>
                        ))}
                        <tr>
                          <td style={{ textAlign: 'left' }}><b>Normalised free cash flow</b></td>
                          <td><b>{big(dcf.diagnostics.base_fcf_quality.normalised_fcf)}</b></td>
                        </tr>
                        <tr>
                          <td style={{ textAlign: 'left' }}>Reported, and used above</td>
                          <td>{big(dcf.assumptions.base_fcf)}</td>
                        </tr>
                      </tbody>
                    </table>
                  )}
                </>
              )}

              {dcf.growth_sensitivity && (
                <>
                  <div className="sens-title">
                    Sensitivity: fair value across the starting growth rate
                    (the grid above holds it at{' '}
                    {(dcf.assumptions.growth_rate_year1 * 100).toFixed(2)}%)
                  </div>
                  <table className="sens-table">
                    <thead>
                      <tr>
                        <th>Growth</th>
                        {dcf.growth_sensitivity.growth_rates.map((g, i) => (
                          <th key={i}>{(g * 100).toFixed(2)}%</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>Fair value</td>
                        {dcf.growth_sensitivity.values.map((v, i) => (
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
                    </tbody>
                  </table>
                  <div className="chart-note">
                    This sweep deliberately ranges outside the 0-25% band the growth
                    <em> input</em> is clamped to. That clamp filters a noisy vendor field;
                    bounding a stress test by it made the band one-sided: a company at 0%
                    growth got upside and no downside, and one at 25% the reverse.
                  </div>
                </>
              )}
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
            [
              'Interest coverage',
              // EBIT and interest are pinned to one period, which is not always
              // the newest — naming the year is what stops a stale-but-honest
              // ratio reading as a current one
              <>
                {num(ratios.solvency.interest_coverage, 1)}
                {ratios.solvency.interest_coverage_period && (
                  <span className="muted-note">
                    {' '}
                    {ratios.solvency.interest_coverage_period.slice(0, 4)}
                  </span>
                )}
              </>,
              'interest_coverage',
            ],
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
