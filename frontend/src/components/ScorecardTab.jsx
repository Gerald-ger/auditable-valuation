import { useEffect, useState } from 'react';
import { get, post, stream } from '../api';
import { num, big, pct, scoreColor } from '../format';
import ScoreHistory from './ScoreHistory';
import Debate from './Debate';

const TIER_COLORS = { S: '#2ebd85', A: '#3b82f6', B: '#f0b90b', C: '#f97316', D: '#f6465d' };

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
    parts.push(`The five pillars are closely balanced (${worst.score}–${best.score}).`);
  }
  if (card.confidence !== 'HIGH') {
    parts.push(`Confidence is ${card.confidence} — only ${card.coverage_pct}% of metrics available.`);
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
            ? 'no metrics available — weight redistributed'
            : `only ${(data.available_fraction * 100).toFixed(0)}% of metrics available — `
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
 * Valuation ranges against the current price.
 *
 * Rebuilt for readability: the price line was previously redrawn inside every
 * row, so it read as a per-row tick rather than one reference; it is now a
 * single rule spanning the plot, with a labelled scale underneath and an
 * explicit verdict per method, since "is the price inside this range?" is the
 * only question the chart exists to answer.
 */
function FootballField({ ranges, currentPrice }) {
  if (!ranges.length) return <div className="chart-note">No valuation ranges available.</div>;
  const lows = ranges.map((r) => r.low).concat(currentPrice ?? []);
  const highs = ranges.map((r) => r.high).concat(currentPrice ?? []);
  const min = Math.min(...lows) * 0.92;
  const max = Math.max(...highs) * 1.05;
  const x = (v) => ((v - min) / (max - min)) * 100;

  // spelled out: "above" alone left it ambiguous whether the price or the range
  // was the thing sitting above
  const verdictFor = (r) => {
    if (!currentPrice) return null;
    if (currentPrice < r.low) return ['price below', 'up'];
    if (currentPrice > r.high) return ['price above', 'down'];
    return ['in range', ''];
  };

  return (
    <div className="ff-chart">
      <div className="ff-plot">
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
        {ranges.map((r) => {
          const v = verdictFor(r);
          return (
            <div key={r.method} className="ff-row">
              <span className="ff-label">{r.method}</span>
              <div className="ff-track">
                <div
                  className="ff-bar"
                  style={{ left: `${x(r.low)}%`, width: `${Math.max(x(r.high) - x(r.low), 1.5)}%` }}
                />
                {r.mid && (
                  <div className="ff-mid" style={{ left: `${x(r.mid)}%` }} title={`Mid ${num(r.mid)}`} />
                )}
              </div>
              <span className="ff-range">
                {num(r.low)} – {num(r.high)}
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
      {currentPrice && (
        <div className="chart-note">
          Bars are the fair-value range each method produces; the tick inside a bar is its
          midpoint. The vertical rule is today&rsquo;s price ({num(currentPrice)}) — a bar sitting
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

  async function loadComps(peers) {
    const q = peers ? `?peer_list=${encodeURIComponent(peers)}` : '';
    setComps(await get(`/stock/${ticker}/comps${q}`));
  }

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
  }, [ticker]);

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
        </div>

        <div className="panel">
          <div className="panel-title">Valuation range (football field)</div>
          {comps ? (
            <FootballField ranges={comps.football_field} currentPrice={comps.current_price} />
          ) : (
            <div className="chart-note">Loading ranges…</div>
          )}
        </div>
      </div>

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
            No peer suggestions for this ticker — type peer tickers above and Apply.
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
