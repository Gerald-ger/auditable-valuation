import { useCallback, useEffect, useState } from 'react';
import { get, post, stream } from '../api';
import { num, big, pct, scoreColor, TIER_COLORS } from '../format';
import ScoreHistory from './ScoreHistory';
import Debate from './Debate';

/**
 * A plain-language read of the card, composed from the pillars themselves.
 *
 * Deliberately computed rather than AI-written: it has to work with Ollama
 * offline, it must never state a figure the engine did not produce, and it must
 * say the same thing every time the same card is rendered.
 */
function verdict(card) {
  const scored = Object.entries(card.pillars)
    .filter(([, p]) => p.score !== null && !p.insufficient)
    .sort((a, b) => b[1].score - a[1].score);
  if (!scored.length) return null;

  const [bestName, best] = scored[0];
  const [worstName, worst] = scored[scored.length - 1];
  const parts = [`${card.tier_label} overall at ${card.composite_score}/100.`];
  if (scored.length > 1 && best.score - worst.score >= 10) {
    parts.push(
      `${bestName[0].toUpperCase()}${bestName.slice(1)} is the strongest pillar (${best.score}), ` +
        `${worstName} the weakest (${worst.score}).`,
    );
  } else {
    parts.push(`The five pillars are closely balanced (${worst.score}-${best.score}).`);
  }
  if (card.confidence !== 'HIGH') {
    parts.push(`Confidence is ${card.confidence}: only ${card.coverage_pct}% of metrics available.`);
  }
  const excluded = Object.entries(card.pillars).filter(([, p]) => p.insufficient);
  if (excluded.length) {
    parts.push(
      `${excluded.map(([n]) => n).join(' and ')} ` +
        `${excluded.length === 1 ? 'was' : 'were'} excluded from the composite.`,
    );
  }
  return parts.join(' ');
}

function PillarBar({ name, data }) {
  const [open, setOpen] = useState(false);
  // A pillar can carry a real score and still be dropped from the composite when
  // under 40% of its metrics are available (scoring.py marks it `insufficient`).
  // Branching on `score === null` alone drew a full-width bar for those, so a
  // pillar could read 97 while contributing nothing — a composite the user
  // could not reconcile with what was on screen.
  if (data.score === null || data.insufficient)
    return (
      <div className="pillar-row">
        <div className="pillar-head">
          <span className="pillar-name">
            {name} <span className="pillar-weight">×{(data.weight * 100).toFixed(0)}%</span>
          </span>
          {data.score !== null && <span className="pillar-score excluded">{data.score}</span>}
        </div>
        <span className="pillar-missing">
          {data.score === null
            ? 'no metrics available, weight redistributed'
            : `only ${(data.available_fraction * 100).toFixed(0)}% of metrics available, `
              + 'excluded from the composite, weight redistributed'}
        </span>
      </div>
    );
  return (
    <div className="pillar-row" onClick={() => setOpen(!open)}>
      <div className="pillar-head">
        <span className="pillar-name">
          {name} <span className="pillar-weight">×{(data.weight * 100).toFixed(0)}%</span>
        </span>
        <span className="pillar-score" style={{ color: scoreColor(data.score) }}>
          {data.score}
        </span>
      </div>
      <div className="pillar-track">
        <div
          className="pillar-fill"
          style={{ width: `${data.score}%`, background: scoreColor(data.score) }}
        />
      </div>
      {open && (
        <table className="metric-detail">
          <tbody>
            {Object.entries(data.metrics).map(([m, v]) => (
              <tr key={m}>
                <td>{m.replaceAll('_', ' ')}</td>
                <td>{num(v.raw, 3)}</td>
                <td style={{ color: scoreColor(v.score) }}>{v.score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/**
 * How far our number is from the price, as arithmetic rather than as a verdict.
 *
 * The residual is labelled unexplained and left that way. It is not a modelling
 * error to be absorbed — it is the market pricing a longer advantage period, a
 * lower discount rate or a higher terminal cash conversion than a ten-year fade
 * to 2.5% can express. Naming the size of that bet is the output. Closing it by
 * tuning would turn the DCF into an expensive way of displaying the price.
 */
function PriceGapBridge({ bridge }) {
  const above = bridge.residual_direction === 'market_above';
  return (
    <div className="gap-bridge">
      <div className="gap-bridge-title">Why our value differs from the price</div>
      <table className="gap-bridge-table">
        <tbody>
          {bridge.steps.map((s) => (
            <tr key={s.label} className={s.kind === 'adjustment' ? 'gap-adj' : ''}>
              <td>{s.kind === 'adjustment' ? '+ ' : ''}{s.label}</td>
              <td>{s.kind === 'adjustment' && s.value > 0 ? '+' : ''}{num(s.value)}</td>
            </tr>
          ))}
          <tr className="gap-subtotal">
            <td>= adjusted value</td>
            <td>{num(bridge.adjusted)}</td>
          </tr>
          <tr>
            <td>Market price</td>
            <td>{num(bridge.price)}</td>
          </tr>
          <tr className="gap-residual">
            <td>Unexplained gap</td>
            <td>
              {bridge.residual > 0 ? '+' : ''}{num(bridge.residual)}
              {bridge.residual_pct != null
                && <span className="muted-note"> ({bridge.residual_pct > 0 ? '+' : ''}
                  {bridge.residual_pct}%)</span>}
            </td>
          </tr>
        </tbody>
      </table>
      <div className="chart-note">
        This gap is not a rounding error in the model. It is a disagreement.{' '}
        {above ? (
          <>To pay today&rsquo;s price you have to believe at least one of: the
            company&rsquo;s advantage runs well beyond our ten-year window, the right
            discount rate is below our CAPM figure, or terminal cash conversion
            exceeds today&rsquo;s.</>
        ) : (
          <>The market is paying <b>less</b> than our adjusted value, so the
            disagreement runs the other way: it is pricing a shorter runway, a
            higher required return, or a risk the accounts do not carry.</>
        )}{' '}
        We leave it unexplained rather than close it, because a model tuned until
        it agreed with the price would only be telling you the price.
      </div>
    </div>
  );
}

/**
 * The analyst target, shown beneath the pillars and scored by none of them.
 *
 * It sits here rather than somewhere quieter on purpose: this is the panel a
 * reader consults to find out what moved the grade, so it is the one place
 * worth saying that this number did not. The football field already treats
 * analyst targets as context; the pillars now agree.
 */
function AnalystContext({ data }) {
  if (!data || data.target_mean == null) return null;
  const pct = data.upside == null ? null : (data.upside * 100).toFixed(1);
  return (
    <div className="analyst-context">
      <div className="analyst-context-head">
        <span>Analyst target</span>
        <span className="analyst-context-value">
          {num(data.target_mean)}
          {pct !== null && <> · <b>{pct > 0 ? '+' : ''}{pct}%</b> vs price</>}
        </span>
      </div>
      <div className="analyst-context-note">
        {data.analysts != null && `${data.analysts} analysts`}
        {data.recommendation && ` · ${data.recommendation}`}
        {data.upside == null && data.analysts != null && data.analysts < 4
          && ' · too few for a range'}
        {'. '}
        <b>not included in any score.</b> A target price is a twelve-month
        forecast of where the stock will trade, not an estimate of what the
        business is worth, and published targets sit above price on average.
        Shown so you can see it; excluded so it cannot quietly move your grade.
      </div>
    </div>
  );
}

// Narrower than this and a bar would render as nothing, so it is held open —
// and marked, since a bar wider than its data misleads exactly where the data
// is thinnest.
const MIN_BAR_WIDTH = 1.5;

/**
 * Valuation ranges against the current price.
 *
 * Rebuilt for readability: the price line was previously redrawn inside every
 * row, so it read as a per-row tick rather than one reference; it is now a
 * single rule spanning the plot, with a labelled scale underneath and an
 * explicit verdict per method, since "is the price inside this range?" is the
 * only question the chart exists to answer.
 */
function FootballField({ ranges, currentPrice, triangulation }) {
  if (!ranges.length) return <div className="chart-note">No valuation ranges available.</div>;
  const drawn = ranges.filter((r) => !r.not_applicable);
  const skipped = ranges.filter((r) => r.not_applicable);
  // The scale belongs to the methods that carry a verdict. Analyst targets are
  // excluded from the overlap and the conviction grade, and were still setting
  // both ends of the axis: measured 2026-08-12 across eight tickers they set the
  // high end on six and were the widest bar on five — up to 87% of the plot,
  // against a voting peer bar at 5.9%. A row that cannot vote must not frame the
  // picture. The envelope, where a method has one, still sets the domain so the
  // outer spread does not fall off the edge of its own chart.
  const scaled = drawn.filter((r) => !r.context_only);
  const domain = scaled.length ? scaled : drawn;
  const lows = domain.map((r) => r.envelope_low ?? r.low).concat(currentPrice ?? []);
  const highs = domain.map((r) => r.envelope_high ?? r.high).concat(currentPrice ?? []);
  const min = Math.min(...lows) * 0.92;
  const max = Math.max(...highs) * 1.05;
  const x = (v) => ((v - min) / (max - min)) * 100;

  /**
   * Bar geometry in plot percent, clipped to the axis.
   *
   * A context row can now run past either edge, and a genuinely narrow range
   * would otherwise render as nothing. Both cases are drawn *and* marked: a cut
   * edge is squared off, and a bar held open at MIN_BAR_WIDTH is outlined,
   * because a bar wider than its data is a lie the reader cannot see. The exact
   * numbers print in the right-hand column regardless.
   */
  const geom = (lo, hi) => {
    const l = x(lo);
    const h = x(hi);
    const left = Math.max(l, 0);
    const right = Math.min(h, 100);
    const width = right - left;
    return {
      visible: width >= 0 && right > 0 && left < 100,
      left,
      width: Math.max(width, MIN_BAR_WIDTH),
      clipLeft: l < 0,
      clipRight: h > 100,
      exaggerated: width < MIN_BAR_WIDTH,
    };
  };

  // spelled out: "above" alone left it ambiguous whether the price or the range
  // was the thing sitting above
  const verdictFor = (r) => {
    if (!currentPrice) return null;
    if (currentPrice < r.low) return ['price below', 'up'];
    if (currentPrice > r.high) return ['price above', 'down'];
    return ['in range', ''];
  };

  const t = triangulation;
  return (
    <div className="ff-chart">
      <div className="ff-plot">
        {/* The agreement zone sits under the bars rather than beside them: the
            spec calls it "the defensible fair-value band", and a reader should
            see it as the place the methods land on, not as a fourth method. */}
        {t?.overlap && (
          <div
            className="ff-overlap"
            style={{
              left: `calc(var(--ff-label) + var(--ff-gap) + (100% - var(--ff-label) - var(--ff-range) - var(--ff-gap) * 2) * ${x(t.overlap.low) / 100})`,
              width: `calc((100% - var(--ff-label) - var(--ff-range) - var(--ff-gap) * 2) * ${(x(t.overlap.high) - x(t.overlap.low)) / 100})`,
            }}
            title={`Methods agree between ${num(t.overlap.low)} and ${num(t.overlap.high)}`}
          />
        )}
        {currentPrice && (
          // the rule must line up with the track, which is inset by the label and
          // range columns — so position it against those explicit widths
          <div
            className="ff-price-rule"
            style={{
              left:
                'calc(var(--ff-label) + var(--ff-gap) + ' +
                `(100% - var(--ff-label) - var(--ff-range) - var(--ff-gap) * 2) * ${x(currentPrice) / 100})`,
            }}
          >
            <span className="ff-price-tag">{num(currentPrice)}</span>
          </div>
        )}
        {drawn.map((r) => {
          const v = verdictFor(r);
          const hasEnvelope = r.envelope_low != null && r.envelope_high != null
            && (r.envelope_low < r.low || r.envelope_high > r.high);
          return (
            <div key={r.method} className={`ff-row ${r.context_only ? 'ff-row-context' : ''}`}>
              <span className="ff-label" title={r.context_only
                ? 'Context only: a target is a forecast of the price, not a valuation of the business. Excluded from the agreement zone.'
                : undefined}
              >
                {r.method}
                {r.independent === false && <span className="ff-tag" title="This method's growth rate comes from analyst consensus, so it is not independent of the analyst-target row.">shared input</span>}
                {r.context_only && <span className="ff-tag">context</span>}
                {/* The range does not vote, but its width measures how much
                    informed forecasters disagree — which nothing else here
                    captures, and which was previously discarded outright. */}
                {r.dispersion_band && (
                  <span
                    className={`ff-tag disp-${r.dispersion_band}`}
                    title={`${r.analysts} analysts span ${(r.dispersion * 100).toFixed(0)}% of the mean target, ${r.dispersion_band} agreement. Measured across 20 large caps this ranges from 15% to 106%.`}
                  >
                    {r.dispersion_band} ±{(r.dispersion * 100).toFixed(0)}%
                  </span>
                )}
                {/* the peer count overstates support when a peer's multiple was
                    negative or missing and dropped out of that median */}
                {r.peers_min != null && r.peers_min < (r.peers_used ?? 0) && (
                  <span
                    className="ff-tag"
                    title={`${r.peers_used} peers resolved, but the thinnest multiple plotted rests on only ${r.peers_min}.`}
                  >
                    {r.peers_min}/{r.peers_used} peers
                  </span>
                )}
              </span>
              <div className="ff-track">
                {/* the outer spread of the method, drawn behind the core so a
                    single multiple that does not transfer cannot silently set
                    the width the verdict is read from */}
                {hasEnvelope && (() => {
                  const e = geom(r.envelope_low, r.envelope_high);
                  return e.visible && (
                    <div
                      className={`ff-envelope ${e.clipLeft ? 'clip-left' : ''} ${e.clipRight ? 'clip-right' : ''}`}
                      style={{ left: `${e.left}%`, width: `${e.width}%` }}
                      title={`Full spread ${num(r.envelope_low)}-${num(r.envelope_high)} across ${r.multiples_used} multiples`}
                    />
                  );
                })()}
                {(() => {
                  const b = geom(r.low, r.high);
                  return b.visible && (
                    <div
                      className={`ff-bar ${b.clipLeft ? 'clip-left' : ''} ${b.clipRight ? 'clip-right' : ''} ${b.exaggerated ? 'ff-bar-exaggerated' : ''}`}
                      style={{ left: `${b.left}%`, width: `${b.width}%` }}
                      title={b.exaggerated
                        ? `Held open to stay visible: the actual range is ${num(r.low)} to ${num(r.high)}${r.degenerate ? ', a single estimate with no width at all' : ''}`
                        : undefined}
                    />
                  );
                })()}
                {r.mid != null && x(r.mid) >= 0 && x(r.mid) <= 100 && (
                  <div className="ff-mid" style={{ left: `${x(r.mid)}%` }} title={`Mid ${num(r.mid)}`} />
                )}
              </div>
              <span className="ff-range">
                {num(r.low)}-{num(r.high)}
                {v && <span className={`ff-verdict ${v[1]}`}>{v[0]}</span>}
              </span>
            </div>
          );
        })}
        <div className="ff-row ff-axis">
          <span className="ff-label" />
          <div className="ff-track">
            <span className="ff-tick" style={{ left: '0%' }}>{num(min)}</span>
            <span className="ff-tick mid" style={{ left: '50%' }}>{num((min + max) / 2)}</span>
            <span className="ff-tick end" style={{ left: '100%' }}>{num(max)}</span>
          </div>
          <span className="ff-range" />
        </div>
      </div>
      {/* A method that does not apply is named and struck out rather than
          dropped: a missing row reads as missing data, and the reason is the
          most useful thing on the chart for a bank or a REIT. */}
      {skipped.map((r) => (
        <div key={r.method} className="chart-note ff-skipped">
          <b>{r.method}:</b> not applicable. {r.reason}
        </div>
      ))}

      {/* The arithmetic, ahead of every verdict on this panel. A reader who
          disagrees with a grade has nowhere to go; a reader who disagrees with a
          line in a bridge can point at the line. */}
      {t?.price_gap_bridge && <PriceGapBridge bridge={t.price_gap_bridge} />}

      {/* The conviction grade led this note until it was measured across eleven
          tickers and came back LOW or None on all of them — a three-band grade
          with one value in practice. It still computes, because "these two
          methods systematically disagree" is true and worth saying once, but the
          spread and the two back-solves below are what actually vary, so they
          lead now. */}
      {t?.conviction && (
        <div className="chart-note">
          {t.overlap ? (
            <>The methods agree between <b>{num(t.overlap.low)}</b> and{' '}
              <b>{num(t.overlap.high)}</b>. That band, not any single bar, is the defensible
              fair value.</>
          ) : (
            <><b>The methods do not overlap at all.</b> No price is considered fair by both{' '}
              {t.anchors?.low_method} and {t.anchors?.high_method}, so this chart cannot give
              you a fair value, only what the disagreement is about.</>
          )}
          {t.midpoint_spread != null && (
            <> Midpoints sit <b>{(t.midpoint_spread * 100).toFixed(0)}%</b> apart
              ({t.anchors?.low_method} {num(t.anchors?.low_mid)} vs {t.anchors?.high_method}{' '}
              {num(t.anchors?.high_mid)}),{' '}
              <span className={`ff-conviction ${t.conviction.toLowerCase()}`}>
                {t.conviction} conviction
              </span>.</>
          )}
          {t.conviction === 'LOW' && (
            <span className="muted-note">
              {' '}A discounted cash flow and trading comps measure different things, so LOW is
              the usual reading here rather than a warning about this company in particular.
              The figures below are the ones that vary.
            </span>
          )}
          {/* Separate axis of uncertainty: conviction says whether the methods
              agree, this says whether the forecasters do. */}
          {t.analyst_dispersion_band && (
            <> Separately, {t.analysts} analysts span{' '}
              <b>{(t.analyst_dispersion * 100).toFixed(0)}%</b> of their own mean,{' '}
              <b>{t.analyst_dispersion_band}</b> agreement on the outlook
              {t.analyst_dispersion_band === 'wide'
                && ', so the forecast itself is contested, not just the valuation method'}.</>
          )}
        </div>
      )}

      {/* Why the DCF and the market differ, named. Measured across eighteen
          large caps, half the time there is no gap worth explaining — so when
          there is one, saying which assumption carries it is the useful act. */}
      {t?.price_reconciliation?.reason && t.price_reconciliation.verdict !== 'aligned' && (
        <div className={`chart-note ff-divergence ff-recon-${t.price_reconciliation.verdict}`}>
          <b>Why the DCF differs from the price:</b> {t.price_reconciliation.reason}
        </div>
      )}

      {/* The whole point of the divergent case: name the assumption, because
          averaging two anchors that disagree by half is false precision. */}
      {t?.diverged && t?.reconciling_growth != null && (
        <div className="chart-note ff-divergence">
          <b>What separates them:</b> the DCF compounds at{' '}
          <b>{(t.growth_used * 100).toFixed(1)}%</b>
          {t.growth_source === 'analyst_consensus_fwd' && ' taken from analyst consensus'}.
          {' '}It agrees with the peer multiples at <b>{(t.reconciling_growth * 100).toFixed(1)}%</b>.
          {' '}So the question is not which bar to believe. It is whether this company grows
          faster than {(t.reconciling_growth * 100).toFixed(1)}% a year. Decide that, and the
          chart resolves itself.
        </div>
      )}

      {/* Second, independent reading of the same disagreement. The DCF sits
          below comps on most companies because a 2.5% perpetuity cannot express
          a 20x+ multiple — not because those companies are expensive. Naming the
          growth today's price already assumes says which of the two it is. */}
      {t?.market_implied_terminal_growth != null && (
        <div className="chart-note ff-divergence">
          <b>What today&rsquo;s price already assumes:</b> to justify it with a perpetuity, free
          cash flow has to compound at{' '}
          <b>{(t.market_implied_terminal_growth * 100).toFixed(2)}%</b> forever
          {t.market_implied_growth_high ? (
            <>, above the {(t.nominal_gdp_growth * 100).toFixed(0)}% an economy grows long-run.
              The market is pricing growth above the economy in perpetuity; the DCF cannot express
              that, which is most of why the two bars disagree.</>
          ) : (
            <>, below the {(t.nominal_gdp_growth * 100).toFixed(0)}% an economy grows long-run,
              so the price needs nothing unusual to hold. Here the gap between the bars is about
              the forecast, not the terminal assumption.</>
          )}
        </div>
      )}

      {currentPrice && (
        <div className="chart-note">
          Bars are the fair-value range each method produces; the tick inside a bar is its
          midpoint, and the faint outer bar is the method&rsquo;s full spread where it has one.
          The vertical rule is today&rsquo;s price ({num(currentPrice)}). A bar sitting
          entirely to its right means that method sees the stock as cheap.
        </div>
      )}
    </div>
  );
}

export default function ScorecardTab({ ticker, aiOnline }) {
  const [card, setCard] = useState(null);
  const [comps, setComps] = useState(null);
  const [peerInput, setPeerInput] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [narrative, setNarrative] = useState(null);
  const [narrativeBusy, setNarrativeBusy] = useState(false);
  const [history, setHistory] = useState([]);
  const [watched, setWatched] = useState(false);

  // useCallback so the effect below can depend on it honestly. As a plain
  // function it was rebuilt every render, so listing it would have re-fetched on
  // every render and leaving it out was the lint warning this file shipped with.
  // Its only changing input is `ticker`, so the identity now moves exactly when
  // the effect's own dependency does — same behaviour, one fewer suppression.
  const loadComps = useCallback(async (peers) => {
    const q = peers ? `?peer_list=${encodeURIComponent(peers)}` : '';
    setComps(await get(`/stock/${ticker}/comps${q}`));
  }, [ticker]);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setCard(null);
    setComps(null);
    setNarrative(null);
    setHistory([]);
    setWatched(false);
    (async () => {
      try {
        const [scoreCard, peerSuggest] = await Promise.all([
          get(`/score/${ticker}`),
          get(`/stock/${ticker}/peers`),
        ]);
        setCard(scoreCard);
        setPeerInput(peerSuggest.suggested.join(', '));
        // after scoring, so today's snapshot is already in the series
        get(`/score/${ticker}/history`)
          .then((h) => setHistory(h.history))
          .catch(() => setHistory([]));
        await loadComps(peerSuggest.suggested.join(','));
      } catch (e) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    })();
  }, [ticker, loadComps]);

  async function explain() {
    setNarrativeBusy(true);
    setNarrative('');
    try {
      await stream(`/score/${ticker}/narrative`, {}, (e) => {
        if (e.error) setNarrative(`⚠ ${e.message}`);
        else setNarrative((prev) => (prev ?? '') + e.delta);
      });
    } catch (e) {
      setNarrative(`⚠ ${e.message}`);
    } finally {
      setNarrativeBusy(false);
    }
  }

  async function addToWatchlist() {
    try {
      await post('/portfolio/position', { ticker, shares: 0 });
      setWatched(true);
    } catch (e) {
      setError(e.message);
    }
  }

  /**
   * Forensic checks — shown beside the score, deliberately not inside it.
   *
   * Each row prints its published threshold next to the value, because these
   * only mean anything against their own literature: a Piotroski 6 is
   * "middling" and a 7 is "strong", and nothing on the card would tell you that
   * otherwise. Checks that do not apply say so with the reason rather than
   * rendering a dash the reader has to interpret.
   */
  function ForensicPanel({ data }) {
    const bandClass = (band) =>
      ({ safe: 'good', strong: 'good', buyback: 'good', low: 'good',
         distress: 'bad', weak: 'bad', dilution: 'bad', high: 'bad' })[band] ?? 'neutral';

    const rows = [
      { key: 'altman_z', label: 'Altman Z',
        hint: 'bankruptcy risk · safe > 2.99, distress < 1.81',
        render: (c) => c.value.toFixed(2) },
      { key: 'piotroski_f', label: 'Piotroski F',
        hint: 'fundamental improvement · strong ≥ 7, weak ≤ 2',
        render: (c) => `${c.value} / ${c.out_of}` },
      { key: 'accrual_ratio', label: 'Accrual ratio',
        hint: '(net income − operating cash flow) / avg assets · lower is better',
        render: (c) => `${(c.value * 100).toFixed(1)}%` },
      { key: 'net_share_issuance', label: 'Net share issuance',
        hint: 'year-on-year diluted share count · negative is a buyback',
        render: (c) => `${c.value > 0 ? '+' : ''}${(c.value * 100).toFixed(1)}%` },
    ];

    return (
      <div className="panel">
        <div className="panel-title">
          Forensic checks
          <span className="chart-note">not included in the score</span>
        </div>
        <table className="comps-table forensic-table">
          <tbody>
            {rows.map(({ key, label, hint, render }) => {
              const c = data[key];
              return (
                <tr key={key}>
                  <td className="forensic-label">
                    {label}
                    <span className="forensic-hint">{hint}</span>
                  </td>
                  <td className="forensic-value">
                    {c.applicable ? render(c) : <span className="forensic-na">n/a</span>}
                  </td>
                  <td className={`forensic-band ${c.applicable ? bandClass(c.band) : 'neutral'}`}>
                    {c.applicable ? c.band : c.note}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="chart-note">{data.note}</div>
      </div>
    );
  }

  if (!ticker) return <div className="empty-state">Enter a ticker above to build a scorecard.</div>;
  if (loading) return <div className="empty-state loading">Scoring fundamentals, valuation and momentum…</div>;
  if (error) return <div className="error-banner">{error}</div>;
  if (!card) return null;

  return (
    <div>
      <div className="panel score-banner">
        <div
          className="tier-badge"
          style={{ background: TIER_COLORS[card.tier] ?? 'var(--border)' }}
        >
          {card.tier ?? '—'}
        </div>
        <div>
          <div className="score-big">
            {card.composite_score ?? '—'}
            <span className="score-outof">/100 · {card.tier_label}</span>
          </div>
          <div className="score-meta">
            {card.ticker} · profile: {card.classification.replaceAll('_', ' ')} · confidence{' '}
            {card.confidence} (coverage {card.coverage_pct}%)
            {card.flags.length > 0 && ` · flags: ${card.flags.join(', ')}`}
          </div>
        </div>
        <div className="banner-actions">
          <button onClick={addToWatchlist} disabled={watched}>
            {watched ? '✓ On watchlist' : '+ Watchlist'}
          </button>
          <button className="primary" onClick={explain} disabled={narrativeBusy || !aiOnline}>
            {narrativeBusy ? 'Explaining…' : aiOnline ? 'Explain with AI' : 'AI offline'}
          </button>
        </div>
      </div>

      {verdict(card) && <div className="panel verdict">{verdict(card)}</div>}

      {narrative !== null && (
        <div className="panel outlook-text">
          {narrative}
          {narrativeBusy && <span className="debate-cursor" />}
        </div>
      )}

      <div className="score-grid">
        <div className="panel">
          <div className="panel-title">Pillar breakdown (click a pillar for metric detail)</div>
          {Object.entries(card.pillars).map(([name, data]) => (
            <PillarBar key={name} name={name} data={data} />
          ))}
          <AnalystContext data={card.analyst_context} />
        </div>

        <div className="panel">
          <div className="panel-title">Valuation range (football field)</div>
          {comps ? (
            <FootballField
              ranges={comps.football_field}
              currentPrice={comps.current_price}
              triangulation={comps.triangulation}
            />
          ) : (
            <div className="chart-note">Loading ranges…</div>
          )}
        </div>
      </div>

      {card.forensics && <ForensicPanel data={card.forensics} />}

      <div className="panel">
        <div className="panel-title">
          Peer comparison
          <span className="peer-edit">
            <input
              value={peerInput}
              onChange={(e) => setPeerInput(e.target.value)}
              placeholder="Peer tickers, comma-separated"
            />
            <button onClick={() => loadComps(peerInput)}>Apply</button>
          </span>
        </div>
        {comps && comps.peers.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table className="comps-table">
              <thead>
                <tr>
                  <th>Company</th><th>Mkt cap</th><th>P/E fwd</th><th>EV/EBITDA</th>
                  <th>EV/Rev</th><th>P/B</th><th>PEG</th><th>Op margin</th><th>Rev growth</th>
                </tr>
              </thead>
              <tbody>
                {[comps.target, ...comps.peers].map((r, i) => (
                  <tr key={r.ticker} className={i === 0 ? 'comps-target' : ''}>
                    <td>{r.ticker}</td>
                    <td>{big(r.market_cap)}</td>
                    <td>{num(r.pe_forward, 1)}</td>
                    <td>{num(r.ev_to_ebitda, 1)}</td>
                    <td>{num(r.ev_to_revenue, 1)}</td>
                    <td>{num(r.price_to_book, 1)}</td>
                    <td>{num(r.peg_ratio, 2)}</td>
                    <td>{pct(r.operating_margin)}</td>
                    <td>{pct(r.revenue_growth)}</td>
                  </tr>
                ))}
                <tr className="comps-median">
                  <td>Peer median</td>
                  <td>—</td>
                  <td>{num(comps.peer_medians.pe_forward, 1)}</td>
                  <td>{num(comps.peer_medians.ev_to_ebitda, 1)}</td>
                  <td>{num(comps.peer_medians.ev_to_revenue, 1)}</td>
                  <td>{num(comps.peer_medians.price_to_book, 1)}</td>
                  <td>{num(comps.peer_medians.peg_ratio, 2)}</td>
                  <td>—</td>
                  <td>—</td>
                </tr>
              </tbody>
            </table>
            {comps.failed_tickers.length > 0 && (
              <div className="chart-note">No data for: {comps.failed_tickers.join(', ')}</div>
            )}
          </div>
        ) : (
          <div className="chart-note">
            No peer suggestions for this ticker. Type peer tickers above and Apply.
          </div>
        )}
      </div>

      <div className="panel">
        <div className="panel-title">Score history (composite vs price when scored)</div>
        <ScoreHistory history={history} />
      </div>

      <Debate ticker={ticker} aiOnline={aiOnline} />

      <div className="caveat">{card.caveat}</div>
    </div>
  );
}
