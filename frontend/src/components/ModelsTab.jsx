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
  // Deliberately NOT in RF_STAND_INS above. It is still China's own curve and
  // therefore still the right currency for CNY cash flows — the thing that set
  // makes muted is "no rate for this currency was used", which is not this. What
  // is missing is freshness, so the label says so and the styling does not.
  cgb_10y_stored_less_spread: 'China 10Y − default spread (last good)',
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
          {/* The figure above is no longer the statement's own: operating cash
              flow adds stock compensation back as non-cash, and the reference
              doc forbids keeping that add-back while the share count stays put
              — it values the same equity twice. Worth 12-19% of fair value on
              the fixtures that report the row, which is far too large to leave
              as an unexplained gap between this number and the filing. Absent
              for an issuer that reports no such row, where the basis says
              `not_reported` rather than zero. */}
          {a.sbc_basis === 'statement_sbc' && (
            <span className="muted-note">
              {' '}less <b>{big(a.fcf_sbc)}</b> stock comp
            </span>
          )}
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

      {/* Named so the headline badge can jump here. The row is the only place
          that says which check failed and why; the badge only says how many. */}
      <div className="dcf-audit-row" id="trust-checks">
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
          {/* How much room the perpetuity has. Deliberately a plain number and
              not a chip: a chip implies a pass/fail line, and there is no
              evidence for where one would sit. The tooltip says what the number
              does instead, which is what lets a reader weigh it — the same
              choice made for the beta regression's R² above. */}
          {d.terminal_spread != null && (
            <span
              className="muted-note"
              title={
                `Terminal value is 1/(WACC − g) times the final year's cash flow, so it is `
                + `${(1 / d.terminal_spread).toFixed(0)}× here, and its sensitivity to a WACC `
                + `error goes as the square of that. A narrow spread does not make the `
                + `valuation wrong; it makes every input behind it matter more.`
              }
            >
              {' · '}WACC − g <b>{pct(d.terminal_spread)}</b>
            </span>
          )}
          {/* An inequality between two computed inputs, not a tuned threshold.
              A lender ranks ahead of a shareholder, so a share cannot require
              less return than the bond above it — CAPM produces it anyway when
              beta × ERP comes in under the credit spread. Reported, never
              corrected: ordering the two would be a modelling change. */}
          {d.cost_of_equity_below_debt && (
            <>
              {' '}
              <span
                className="alert-chip"
                title={
                  // Two decimals, not the usual one: the gap is often a few
                  // basis points — 3.76% against 3.84% on 0002.HK — and at one
                  // decimal the sentence reads "3.8% is below 3.8%".
                  `Cost of equity ${pct(a.cost_of_equity, 2)} is below the pre-tax cost of `
                  + `debt ${pct(d.cost_of_debt_pre_tax, 2)}, which cannot be true of one company: debt `
                  + `ranks ahead of equity. It happens here because beta × ERP is smaller than `
                  + `the credit spread. The figures are shown as computed rather than reordered.`
                }
              >
                cost of equity below cost of debt
              </span>
            </>
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
  // Only shown where the issuer reports the row. An all-zero column on XOM or
  // 0002.HK would be four more numbers that say nothing, on a table already
  // wide enough to overflow a phone.
  const hasSbc = b.history.some((h) => h.sbc_to_revenue > 0);
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
            {hasSbc && <th>Stock comp / revenue</th>}
          </tr>
        </thead>
        <tbody>
          {b.history.map((h, i) => (
            <tr key={h.period} className={i === b.history.length - 1 ? 'base-year-latest' : ''}>
              <td style={{ textAlign: 'left' }}>{h.period.slice(0, 10)}</td>
              <td>{pct(h.operating_margin_cash)}</td>
              <td>{pct(h.capex_to_revenue)}</td>
              <td><b>{pct(h.fcf_margin)}</b></td>
              {hasSbc && <td>{pct(h.sbc_to_revenue)}</td>}
            </tr>
          ))}
          <tr className="base-year-mean">
            <td style={{ textAlign: 'left' }}>{b.periods}-year average</td>
            <td />
            <td />
            <td><b>{pct(b.mean_fcf_margin)}</b></td>
            {hasSbc && <td>{pct(b.mean_sbc_margin)}</td>}
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
        {hasSbc && (
          <>
            {' '}The figure below discounts that average <b>net of the average
            stock-compensation charge</b> — {pct(b.mean_fcf_margin, 2)} −{' '}
            {pct(b.mean_sbc_margin, 2)} ={' '}
            <b>{pct(b.mean_fcf_margin - b.mean_sbc_margin, 2)}</b> of revenue — because a
            normal year carries a normal charge. The headline instead nets the base
            year&rsquo;s own charge, which is the one it actually reported.
            {/* Two decimals, where the table above uses one: these three numbers are
                a subtraction the reader can check, and at one decimal MSFT printed
                26.0 − 4.2 = 21.7 because each term rounded on its own. The stored
                margins carry four places, so two makes it exact rather than merely
                closer. */}
          </>
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
                  On this company&rsquo;s {b.periods}-year average margin
                  {hasSbc && <>, net of stock comp</>}, at today&rsquo;s revenue
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

/* How many of the Trust checks this valuation failed, said where the number
   is rather than where the explanation is.
 *
 * No threshold. A single contradiction is worth surfacing on its own, and
 * picking a cutoff would mean choosing a number the diagnostics do not supply.
 * Measured 2026-08-26: AAPL trips one (market-implied growth), 0002.HK trips
 * two, one of which is the CAPM inversion — so the badge discriminates between
 * them where the caveat rows below render at near-identical density.
 */
function TrustFlagBadge({ dcf }) {
  const d = dcf?.diagnostics;
  if (!d) return null;
  const flags = [
    d.cost_of_equity_below_debt,
    d.terminal_value_high,
    d.market_implied_growth_high,
    d.net_debt_assumed_zero?.length > 0,
    dcf.assumptions?.fx_basis === 'rate_unavailable',
  ].filter(Boolean).length;
  if (!flags) return null;
  return (
    <button
      type="button"
      className={`dcf-flags ${d.cost_of_equity_below_debt ? 'alert' : ''}`}
      title="Jump to Trust checks, which names each one and why it fired."
      onClick={() =>
        document.getElementById('trust-checks')?.scrollIntoView({ block: 'center' })
      }
    >
      {flags} trust check{flags > 1 ? 's' : ''} flagged
    </button>
  );
}

/**
 * The intrinsic valuation for a company the DCF panel below cannot value.
 *
 * A bank has no free cash flow to discount — deposits are raw material rather
 * than capital awaiting reinvestment — and a REIT's `CFO - CapEx` treats
 * property acquisition as maintenance. Both get their own model in
 * `financial_models`, and until now both were invisible here: the tab showed a
 * DCF panel with a banner saying the DCF does not apply, and nothing that did.
 *
 * Read-only on purpose. The DCF panel's inputs recalculate through
 * `POST /stock/{t}/dcf`; there is no equivalent endpoint for these two yet, and
 * rendering controls that cannot recalculate would be worse than none.
 *
 * Rendered *above* the DCF panel rather than inside it. The two are different
 * models with different bridges — this one never forms an enterprise value —
 * and nesting them would invite the comparison the football field deliberately
 * declines to draw.
 */
function IntrinsicPanel({ analysis, ticker }) {
  // Exactly one of the two is non-null for any company: `full_analysis` gates
  // each on `valuation_model_for(classification)`, and that returns one model.
  // An errored model is still an object, so it is picked here and its refusal
  // is what gets rendered — which is the point. "No valuation, and here is the
  // sentence saying why" is the answer for a REIT today.
  const model = analysis.excess_return
    ? 'excess_return'
    : analysis.dividend_discount
      ? 'dividend_discount'
      : null;

  // Declared before the early return below: hooks cannot be called
  // conditionally, and this component renders for companies that have no
  // intrinsic model at all.
  const [driver, setDriver] = useState('');
  const [termGrowth, setTermGrowth] = useState('');
  const [ke, setKe] = useState('');
  const [override, setOverride] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!model) return null;

  const bank = model === 'excess_return';
  // A recalculation replaces what the page loaded with, refusals included. That
  // is the escape hatch the endpoint exists for: O's model declines at its
  // regressed beta of 0.4263, and a reader who thinks that is an artefact of a
  // low-R-squared fit rather than a risk measure can supply a rate and watch
  // what the model does with it — which is the whole difference between a
  // valuation you can read and one you can argue with.
  const v = override ?? analysis[model];
  const title = bank
    ? 'Excess return: residual income on book equity'
    : 'Dividend discount: two-stage, per share';

  async function recalc() {
    setBusy(true);
    try {
      // Empty means "use the measured figure", the convention the DCF controls
      // beneath this panel already use. Sending the displayed number instead
      // would make every recalculation look like a deliberate override.
      const rate = (x) => (x === '' ? null : Number(x) / 100);
      setOverride(await post(`/stock/${ticker}/intrinsic`, {
        [bank ? 'roe' : 'growth_rate']: rate(driver),
        terminal_growth: rate(termGrowth),
        cost_of_equity: rate(ke),
      }));
    } catch (e) {
      setOverride({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  // Built once and rendered in both branches below. Putting them after the
  // refusal branch would leave a REIT that declines at its own cost of equity
  // with no way to supply a different one — the company type that most needs
  // these inputs would be the only one never shown them.
  const controls = (
    <div className="dcf-controls">
      <label>
        {bank ? 'Return on equity %' : 'Dividend growth %'}
        <input
          value={driver}
          placeholder={v.assumptions
            ? ((bank ? v.assumptions.roe : v.assumptions.growth_rate_explicit) * 100)
              .toFixed(2)
            : ''}
          onChange={(e) => setDriver(e.target.value)}
        />
      </label>
      <label>
        Terminal growth %
        <input
          value={termGrowth}
          placeholder={v.assumptions ? (v.assumptions.terminal_growth * 100).toFixed(2) : ''}
          onChange={(e) => setTermGrowth(e.target.value)}
        />
      </label>
      <label>
        Cost of equity %
        <input
          value={ke}
          placeholder={v.assumptions
            ? (v.assumptions.cost_of_equity_used * 100).toFixed(2)
            : ''}
          onChange={(e) => setKe(e.target.value)}
        />
      </label>
      <button className="primary" onClick={recalc} disabled={busy}>
        {busy ? 'Calculating…' : 'Recalculate'}
      </button>
    </div>
  );

  if (v.error) {
    return (
      <div className="panel intrinsic-panel">
        <div className="panel-title">{title}</div>
        <div className="notice-banner">{v.error}</div>
        <div className="chart-note">
          A discounted cash flow does not apply to this company type either, so there is
          no intrinsic fair value on this tab for it — a refusal is a result here, not a
          gap waiting to be filled. The inputs below re-run the model on assumptions you
          supply; what it refuses about arithmetic and seniority it goes on refusing
          whatever you type.
        </div>
        {controls}
      </div>
    );
  }

  const a = v.assumptions;
  const d = v.diagnostics;
  const ccy = a.currency;
  // `big` for both. The excess return model works in aggregate currency and
  // reaches per share only at the last step, so its bridge runs in the hundreds
  // of billions; the dividend model is per share from its first line and its
  // bridge runs in tens. One formatter covers both because `big` abbreviates
  // only above a million and falls through to `num` beneath it — a separate
  // per-share formatter was written first and a mutation proved it changed
  // nothing, which is what removed it.
  const ffo = d?.payout_of_ffo_proxy;
  const ffoLatest = ffo && ffo.length ? ffo[ffo.length - 1].payout_of_ffo_proxy : null;

  return (
    <div className="panel intrinsic-panel">
      <div className="panel-title">
        {title}
        <span className="title-note">
          {a.stage1_years} explicit year{a.stage1_years === 1 ? '' : 's'} +{' '}
          {a.stage2_years}-year fade to terminal
        </span>
      </div>

      <div className="chart-note">
        {bank
          ? 'A bank’s book equity is regulatory capital rather than an accounting artefact, so what a share is worth is what its return on equity earns above the cost of that equity, compounded. Deposits are raw material; there is no free cash flow here to discount.'
          : 'A REIT distributes by statute rather than by choice, so the dividend is the cash flow rather than a residual left after one. Per share throughout — REITs fund acquisitions by issuing equity, and the aggregate dividend grows with the share count as well as with the business.'}
      </div>

      {controls}

      <div className="dcf-result">
        <div>
          <span className="dcf-label">Fair value / share {ccy}</span>
          <span className="dcf-big">{num(v.fair_value_per_share)}</span>
        </div>
        <div>
          <span className="dcf-label">Current price {ccy}</span>
          <span className="dcf-big">{num(v.current_price)}</span>
        </div>
        <div>
          <span className="dcf-label">Upside</span>
          {/* null >= 0 is true in JS — an unavailable upside stays neutral
              rather than rendering green. Same guard as the DCF panel's. */}
          <span
            className={`dcf-big ${v.upside_pct == null ? '' : v.upside_pct >= 0 ? 'up' : 'down'}`}
          >
            {v.upside_pct > 0 ? '+' : ''}
            {num(v.upside_pct, 1)}%
          </span>
        </div>
      </div>

      {/* Where the number comes from, in the order the model builds it. No
          enterprise value and no net debt on either: both reach equity
          directly rather than bridging to it, and printing a bridge they never
          computed would invite a comparison with the DCF that does not exist.

          The unit is named because the two models differ in it — one bridge is
          an aggregate and the other is already per share — and because these
          figures are converted at the output boundary, so on a cross-listed
          issuer they are not the currency the statements were filed in. */}
      <div className="sens-title">
        Where the value comes from &mdash; {ccy}
        {bank ? ', aggregate' : ' per share'}
      </div>
      <div className="dcf-audit">
        {(bank
          ? [
              ['Book value of common equity', big(v.book_value_of_equity)],
              ['+ PV of excess returns', big(v.excess_return_pv)],
              ['+ PV of terminal excess return', big(v.terminal_value_pv)],
              ['= Equity value', big(v.equity_value)],
            ]
          : [
              [`Dividend / share, ${a.dividend_period}`, big(a.dividend_per_share)],
              ['PV of the explicit dividends', big(v.dividend_pv)],
              ['+ PV of the terminal dividend', big(v.terminal_value_pv)],
              ['= Value / share', big(v.fair_value_per_share)],
            ]
        ).map(([label, value]) => (
          <div className="dcf-audit-row" key={label}>
            <span className="dcf-label">{label}</span>
            <span>{value}</span>
          </div>
        ))}
      </div>

      <div className="sens-title">What the model assumes</div>
      <div className="dcf-audit">
        {(bank
          ? [
              [
                'Return on equity',
                pct(a.roe, 2),
                `mean of ${a.roe_periods} reported periods; the newest alone is ${pct(a.roe_latest, 2)}, worth ${num(d.fair_value_latest_roe)} a share`,
              ],
              [
                'Spread over cost of equity',
                pct(d.excess_spread, 2),
                'claimed to persist forever — the single largest assumption here, since competition and regulation should erode it',
              ],
              [
                'Book value growth',
                pct(a.growth_rate_explicit, 2),
                `return on equity times a retention ratio of ${pct(a.retention_ratio, 1)}`,
              ],
              [
                'Payout the terminal phase needs',
                pct(d.implied_terminal_payout, 1),
                `against ${pct(d.current_payout, 1)} paid today — a gap is the model quietly assuming a change of policy`,
              ],
              [
                'Price to book',
                num(d.price_to_book, 3),
                `book value per share ${num(d.book_value_per_share)} ${ccy}${
                  d.tangible_share_of_book == null
                    ? ''
                    : `; ${pct(d.tangible_share_of_book, 1)} of it tangible`
                }`,
              ],
            ]
          : [
              [
                'Dividend growth',
                pct(a.growth_rate_explicit, 2),
                `compounded across ${a.growth_periods + 1} declared dividends; the mean year-on-year reads ${pct(d.growth_mean_yoy, 2)}`,
              ],
              [
                'Cost of equity vs cost of debt',
                pct(d.cost_of_equity_headroom, 2),
                `headroom over a pre-tax cost of debt of ${pct(d.cost_of_debt_pre_tax, 2)}; below zero the model refuses, because a share cannot require less return than the bond above it`,
              ],
              [
                'Cost of equity the price implies',
                pct(d.implied_cost_of_equity, 2),
                'what the market is charging, against what CAPM says below — the gap, not the fair value, is the claim being made',
              ],
              [
                'Dividend against FFO',
                pct(ffoLatest, 1),
                'net income plus total depreciation — a proxy, not NAREIT FFO, since no gain-on-sale row is published',
              ],
              [
                'Trailing dividend yield',
                pct(d.trailing_dividend_yield, 2),
                `share count grew ${pct(d.share_count_growth, 1)} across the reported periods`,
              ],
            ]
        ).map(([label, value, note]) => (
          <div className="dcf-audit-row" key={label}>
            <span className="dcf-label">
              {label}
              {note && <em> — {note}</em>}
            </span>
            <span>{value}</span>
          </div>
        ))}
        <div className="dcf-audit-row">
          <span className="dcf-label">
            Cost of equity <em>— {a.cost_of_equity_source === 'capm' ? 'CAPM' : 'supplied'}</em>
          </span>
          <span>{pct(a.cost_of_equity_used, 2)}</span>
        </div>
        <div className="dcf-audit-row">
          <span className="dcf-label">
            Terminal growth <em>— {a.terminal_growth_source.replaceAll('_', ' ')}</em>
          </span>
          <span>{pct(a.terminal_growth, 2)}</span>
        </div>
        <div className="dcf-audit-row">
          <span className="dcf-label">
            Terminal share of the answer
            {d.terminal_value_high && <em> — above the conventional 75% warning line</em>}
          </span>
          <span className={d.terminal_value_high ? 'down' : ''}>
            {pct(d.terminal_value_share, 1)}
          </span>
        </div>
      </div>

      <div className="sens-title">
        Sensitivity: fair value across cost of equity (rows) ×{' '}
        {bank ? 'return on equity' : 'terminal growth'} (columns)
      </div>
      <table className="sens-table">
        <thead>
          <tr>
            <th>Ke \ {bank ? 'ROE' : 'g'}</th>
            {(bank ? v.sensitivity.roe_cols : v.sensitivity.terminal_growth_cols).map((c) => (
              <th key={c}>{(c * 100).toFixed(2)}%</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {v.sensitivity.rows.map((row) => (
            <tr
              key={row.cost_of_equity}
              className={row.below_cost_of_debt ? 'sens-row-void' : ''}
            >
              <td>{(row.cost_of_equity * 100).toFixed(2)}%</td>
              {/* A row the model would refuse is not painted up or down. The
                  colour says "cheap" or "expensive" against today's price, and
                  a rate the company could not raise equity at has no business
                  making that claim. */}
              {row.values.map((cell, i) => (
                <td
                  key={i}
                  className={
                    cell === null || row.below_cost_of_debt
                      ? ''
                      : cell >= v.current_price
                        ? 'cell-up'
                        : 'cell-down'
                  }
                >
                  {cell === null ? '—' : num(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>

      {v.sensitivity.rows.some((row) => row.below_cost_of_debt) && (
        <div className="chart-note">
          The struck-through rows sit below this company&rsquo;s own pre-tax cost of debt.
          The model computes them so you can see which way the answer moves, and refuses
          to report them as a fair value for the reason it gives when you type one in:
          a lender ranks ahead of a shareholder. Wherever this model draws a football
          field bar, that bar is built from the remaining rows only &mdash; though not from
          the figures on this screen, which are yours: the Scorecard runs the model on
          its own measured inputs.
        </div>
      )}

      {/* Only the dividend model reaches this, and the condition is the data
          rather than a check on which model ran: `growth_sensitivity` is a key
          only `dividend_discount_valuation` returns. The excess return model
          publishes `roe_sensitivity` instead and it is deliberately not drawn —
          its grid already sweeps both first-order inputs, so that sweep is
          literally the grid's middle row, verified element for element on the
          JPM fixture, which is why `comps._excess_return_band` declines to
          union it in too. A `!bank &&` guard stood here until a mutation showed
          it could never change the outcome. */}
      {v.growth_sensitivity && (
        <>
          <div className="sens-title">
            Sensitivity: fair value across the dividend growth rate (the grid above holds
            it at {(a.growth_rate_explicit * 100).toFixed(2)}%)
          </div>
          <table className="sens-table">
            <thead>
              <tr>
                <th>Growth</th>
                {v.growth_sensitivity.growth_rates.map((g, i) => (
                  <th key={i}>{(g * 100).toFixed(2)}%</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Fair value</td>
                {v.growth_sensitivity.values.map((cell, i) => (
                  <td
                    key={i}
                    className={
                      cell === null ? '' : cell >= v.current_price ? 'cell-up' : 'cell-down'
                    }
                  >
                    {cell === null ? '—' : num(cell)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </>
      )}

      <div className="chart-note">
        Every input is empty by default and empty means measured, so recalculating a blank
        form returns exactly the figures already on screen. Nothing bounds what you may
        type, and the terminal share above is what says when a figure has stopped meaning
        anything: a cost of equity near the terminal growth rate puts almost the whole
        valuation in the perpetuity, and the model flags that past 75% rather than
        refusing it. An invented ceiling would only have hidden the same arithmetic.
        {a.fx_basis === 'converted' && (
          <>
            {' '}Every figure above is converted from {a.reporting_currency} at{' '}
            {num(a.fx_rate_used, 4)}; the ratios are unit-free and are not.
          </>
        )}
        {a.fx_basis === 'rate_unavailable' && (
          <>
            {' '}No rate was available between the reporting and trading currencies, so the
            comparison with price is withheld rather than made across two units.
          </>
        )}
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

      {/* Above the DCF panel, not below it: for these company types the DCF
          panel's own banner says it does not apply, and the model that does
          apply should be the one the reader meets first. */}
      <IntrinsicPanel analysis={analysis} ticker={ticker} />

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
          <div className="notice-banner">
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
          /* An override the model could not run is the user's own input coming
             back at them. It wore the AI-outage banner, which said the wrong
             thing about whose problem it was. */
          <div className="error-banner">{dcf.error}</div>
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
                  <TrustFlagBadge dcf={dcf} />
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
