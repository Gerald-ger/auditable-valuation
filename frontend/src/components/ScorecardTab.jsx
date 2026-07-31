import { useEffect, useState } from 'react';
import { get, post } from '../api';
import { num, big, pct } from '../format';

const TIER_COLORS = { S: '#2ebd85', A: '#3b82f6', B: '#f0b90b', C: '#f97316', D: '#f6465d' };

const scoreColor = (s) => (s >= 65 ? '#2ebd85' : s >= 50 ? '#f0b90b' : '#f6465d');

function PillarBar({ name, data }) {
  const [open, setOpen] = useState(false);
  if (data.score === null)
    return (
      <div className="pillar-row">
        <span className="pillar-name">{name}</span>
        <span className="pillar-missing">insufficient data (weight redistributed)</span>
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

function FootballField({ ranges, currentPrice }) {
  if (!ranges.length) return <div className="chart-note">No valuation ranges available.</div>;
  const lows = ranges.map((r) => r.low).concat(currentPrice ?? []);
  const highs = ranges.map((r) => r.high).concat(currentPrice ?? []);
  const min = Math.min(...lows) * 0.92;
  const max = Math.max(...highs) * 1.05;
  const x = (v) => ((v - min) / (max - min)) * 100;
  return (
    <div className="ff-chart">
      {ranges.map((r) => (
        <div key={r.method} className="ff-row">
          <span className="ff-label">{r.method}</span>
          <div className="ff-track">
            <div
              className="ff-bar"
              style={{ left: `${x(r.low)}%`, width: `${Math.max(x(r.high) - x(r.low), 1)}%` }}
            />
            {r.mid && <div className="ff-mid" style={{ left: `${x(r.mid)}%` }} />}
            {currentPrice && <div className="ff-price" style={{ left: `${x(currentPrice)}%` }} />}
          </div>
          <span className="ff-range">
            {num(r.low)} – {num(r.high)}
          </span>
        </div>
      ))}
      {currentPrice && (
        <div className="chart-note">
          ─ bars: fair-value range per method · ▎white line: current price {num(currentPrice)}
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
    (async () => {
      try {
        const [scoreCard, peerSuggest] = await Promise.all([
          get(`/score/${ticker}`),
          get(`/stock/${ticker}/peers`),
        ]);
        setCard(scoreCard);
        setPeerInput(peerSuggest.suggested.join(', '));
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
    try {
      const res = await post(`/score/${ticker}/narrative`);
      setNarrative(res.reply ?? `⚠ ${res.message ?? 'Local AI unavailable.'}`);
    } catch (e) {
      setNarrative(`⚠ ${e.message}`);
    } finally {
      setNarrativeBusy(false);
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
        <button className="primary explain-btn" onClick={explain} disabled={narrativeBusy || !aiOnline}>
          {narrativeBusy ? 'Explaining…' : aiOnline ? 'Explain with AI' : 'AI offline'}
        </button>
      </div>

      {narrative && <div className="panel outlook-text">{narrative}</div>}

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

      <div className="caveat">{card.caveat}</div>
    </div>
  );
}
