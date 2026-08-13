import { num } from '../format';

/**
 * Composite score against the price recorded at scoring time.
 *
 * This is the point of persisting scores at all: the anchor tables in
 * scoring.py are hand-set heuristics, and until you can see a score next to
 * what the price did afterwards there is no way to tell whether they are
 * calibrated or merely plausible. Each series is scaled to its own range —
 * read the *shapes* against each other, not the absolute heights.
 */
export default function ScoreHistory({ history }) {
  if (!history || history.length === 0) {
    return (
      <div className="chart-note">
        No snapshots yet. Every time you score this ticker a dated row is stored, so
        this fills in on its own.
      </div>
    );
  }
  if (history.length < 2) {
    return (
      <div className="chart-note">
        1 snapshot so far ({history[0].as_of_date}: score {history[0].composite}, price{' '}
        {num(history[0].price)}). A trend needs at least two. Come back after the next
        scoring day.
      </div>
    );
  }

  const W = 100;
  const H = 40;
  const path = (values) => {
    const clean = values.map((v) => (v === null || v === undefined ? null : v));
    const present = clean.filter((v) => v !== null);
    if (present.length < 2) return null;
    const min = Math.min(...present);
    const max = Math.max(...present);
    const span = max - min || 1;
    return clean
      .map((v, i) => {
        if (v === null) return null;
        const x = (i / (clean.length - 1)) * W;
        const y = H - ((v - min) / span) * H;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .filter(Boolean)
      .join(' ');
  };

  const scoreLine = path(history.map((r) => r.composite));
  const priceLine = path(history.map((r) => r.price));
  const first = history[0];
  const last = history[history.length - 1];
  const scoreDelta = last.composite - first.composite;
  const priceDelta =
    first.price && last.price ? (last.price / first.price - 1) * 100 : null;

  return (
    <div>
      <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {priceLine && (
          <polyline
            points={priceLine}
            fill="none"
            stroke="var(--muted)"
            strokeWidth="1.5"
            strokeDasharray="3 2"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {scoreLine && (
          <polyline
            points={scoreLine}
            fill="none"
            stroke="var(--accent)"
            strokeWidth="2"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      <div className="spark-legend">
        <span>
          <i className="swatch score" /> composite {first.composite} → {last.composite} (
          {scoreDelta >= 0 ? '+' : ''}
          {scoreDelta})
        </span>
        <span>
          <i className="swatch price" /> price {num(first.price)} → {num(last.price)}
          {priceDelta !== null && (
            <span className={priceDelta >= 0 ? 'up' : 'down'}>
              {' '}
              ({priceDelta >= 0 ? '+' : ''}
              {priceDelta.toFixed(1)}%)
            </span>
          )}
        </span>
      </div>

      <table className="history-table">
        <thead>
          <tr>
            <th>Date</th><th>Score</th><th>Tier</th><th>Conf</th><th>Price</th>
          </tr>
        </thead>
        <tbody>
          {[...history].reverse().slice(0, 8).map((r) => (
            <tr key={r.as_of_date}>
              <td>{r.as_of_date}</td>
              <td>{r.composite}</td>
              <td>{r.tier}</td>
              <td>{r.confidence}</td>
              <td>{num(r.price)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="chart-note">
        Scores are a snapshot, not a forecast. This chart shows what happened; it does
        not validate the method. {history.length} snapshot{history.length === 1 ? '' : 's'} stored.
      </div>
    </div>
  );
}
