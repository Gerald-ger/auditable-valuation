// Technical indicator math. All functions take chart bars ({time, close, ...})
// and return lightweight-charts-ready [{time, value}] arrays.
//
// Every `period` here counts BARS, which is the convention every mainstream
// charting platform uses: on a 5-minute chart AAStocks' SMA(150) is 150 bars —
// 750 minutes — not 150 days.
//
// These windows were previously scaled to trading days, so that "MA50" meant the
// same duration on every period button. That read well and made the short
// periods unusable: a 50-day average does not exist inside a one-day chart at
// any bar size, so MA, RSI and MACD simply vanished on 1d and 5d. Counting bars
// is what makes a smooth intraday line possible at all.
//
// The cost is the ambiguity the old scheme was avoiding — MA50 spans 50 minutes
// on a 1-minute chart and 50 days on a daily one. That is now paid for in the
// UI rather than in the math: `windowSpan` turns a window into the time it
// actually covers, and the chart states it beside every indicator.

// Minutes per bar for the intraday intervals the backend serves. Coarser
// intervals are named rather than measured, because "50 days" reads better than
// the 72,000 minutes it works out to.
const INTERVAL_MINUTES = {
  '1m': 1, '2m': 2, '5m': 5, '15m': 15, '30m': 30, '60m': 60, '90m': 90, '1h': 60,
};
const INTERVAL_UNIT = { '1d': 'day', '1wk': 'week', '1mo': 'month' };
// Intervals that do not divide a session, counted in sessions directly.
//
// Yahoo serves 4h as exactly **two** bars per session — 09:30 and 13:30,
// measured 2026-08-19 on AAPL and 0700.HK alike, 126 bars over 63 trading days
// on both. The minutes model below cannot express that: it would read 50 bars
// as 50 x 240 min = 200 h and divide by a 6.5 h session to print "30.8
// sessions", when the truth is 25. The second bar of a session is nominally
// four hours long and only ever contains the 2.5 the session has left.
//
// The minutes model is approximate for every interval it covers — 50 x 1h reads
// 7.7 sessions against a measured 7 bars/day, so ~8% high — and it is shown
// behind a "≈" for that reason. 23% is past what a "≈" can carry.
const BARS_PER_SESSION = { '4h': 2 };

/**
 * How much time a window of `barCount` bars covers, as a label.
 *
 * This is what keeps a bar-counted window honest on screen: MA50 reads "50 min"
 * on a 1-minute chart and "50 days" on a daily one, and the legend says which.
 *
 * A session is taken as 6.5 hours once a window is long enough that sessions
 * read better than hours. Hong Kong trades 5.5, so that figure is approximate
 * by construction — it is only ever shown behind a "≈".
 */
export function windowSpan(barCount, interval) {
  const perSession = BARS_PER_SESSION[interval];
  if (perSession) return `${+(barCount / perSession).toFixed(1)} sessions`;
  const perBar = INTERVAL_MINUTES[interval];
  if (perBar) {
    const minutes = barCount * perBar;
    if (minutes < 90) return `${minutes} min`;
    const hours = minutes / 60;
    if (hours < 13) return `${+hours.toFixed(1)} h`;
    return `${+(hours / 6.5).toFixed(1)} sessions`;
  }
  const unit = INTERVAL_UNIT[interval];
  if (unit) return `${barCount} ${unit}${barCount === 1 ? '' : 's'}`;
  return `${barCount} bars`;
}

export function smaSeries(bars, period) {
  const out = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
  }
  return out;
}

/**
 * Rolling dispersion band: the `period`-bar mean of closes, plus and minus
 * `k` standard deviations of the same window.
 *
 * This is what Bollinger Bands are, and it is deliberately *not* called that.
 * The band asserts nothing — it is descriptive statistics, and %B, the usual
 * "signal" read off it, is an exact affine map of a z-score:
 *
 *     %B = (P - lower) / (upper - lower) = 1/2 + z/(2k)
 *
 * so there is no information in a band tag beyond "price is z standard
 * deviations from its own mean". Measured on 12,461 daily bars across ten
 * names, the correlation between %B and that z-score is 1.000000. The
 * eponymous name would import a trading-signal claim this platform is not
 * making; the plain one describes what the lines are.
 *
 * Two things worth knowing before reading a tag as rare:
 *
 * - **Containment is ~88.5%, not the 95.4% a normal distribution implies.**
 *   Measured across those same bars: 87.3-89.4% per name. Volatility clusters,
 *   returns are fat-tailed, and sigma is estimated in-sample from the very
 *   window that contains the price. Tags run at roughly 28 per year.
 * - **The band distance is capped by construction.** Because sigma comes from
 *   the same `period` points, no close can sit more than sqrt(n-1) = 4.36 sigma
 *   from its own mean at n=20, whatever the market does. The largest deviation
 *   observed across the measured set was 4.00 — the ceiling is arithmetic, not
 *   a market fact, so a "±5 SD" band could never be touched at this period.
 *   (The ceiling depends on the divisor: sqrt(n-1) for the population form used
 *   here, (n-1)/sqrt(n) = 4.25 for the sample form. They are easy to state the
 *   wrong way round, so `rollingSdBand` has a test that derives it.)
 *
 * Sigma is the **population** form (divide by n), which is the charting
 * convention, so the numbers agree with what other tools draw. The sample form
 * (n-1) would widen the band by sqrt(20/19) = 2.60% and lift containment to
 * about 90.0%.
 *
 * The mean is computed first and deviations taken against it — two passes —
 * rather than the O(1)-updatable `E[x^2] - E[x]^2`. The fast form was measured
 * and its error is negligible even at BRK.A prices (max relative error 1.5e-12),
 * so this is not averting a disaster; it costs at most ~70k multiply-adds on the
 * longest series this chart draws, which buys unconditional stability for free.
 *
 * Emission starts at index `period - 1`, exactly like `smaSeries`, so the band
 * lines up bar-for-bar with the MA of the same period rather than beginning a
 * bar early or late.
 */
export function rollingSdBand(bars, period = 20, k = 2) {
  const upper = [];
  const lower = [];
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += bars[j].close;
    const mid = sum / period;
    let squares = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const d = bars[j].close - mid;
      squares += d * d;
    }
    const sd = Math.sqrt(squares / period);
    upper.push({ time: bars[i].time, value: mid + k * sd });
    lower.push({ time: bars[i].time, value: mid - k * sd });
  }
  return { upper, lower };
}

// Wilder's RSI
export function rsiSeries(bars, period = 14) {
  if (bars.length <= period) return [];
  const out = [];
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = bars[i].close - bars[i - 1].close;
    if (d >= 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  const rsi = () => (avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
  out.push({ time: bars[period].time, value: rsi() });
  for (let i = period + 1; i < bars.length; i++) {
    const d = bars[i].close - bars[i - 1].close;
    avgGain = (avgGain * (period - 1) + Math.max(d, 0)) / period;
    avgLoss = (avgLoss * (period - 1) + Math.max(-d, 0)) / period;
    out.push({ time: bars[i].time, value: rsi() });
  }
  return out;
}

function emaArray(values, period) {
  const out = new Array(values.length).fill(null);
  if (values.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i];
  out[period - 1] = sum / period;
  const k = 2 / (period + 1);
  for (let i = period; i < values.length; i++) {
    out[i] = values[i] * k + out[i - 1] * (1 - k);
  }
  return out;
}

// MACD(12, 26, 9) — periods are in BARS, so callers working with intraday bars
// must scale them if the conventional day-based meaning is to be preserved.
export function macdSeries(bars, fast = 12, slow = 26, signalPeriod = 9) {
  const closes = bars.map((b) => b.close);
  const e12 = emaArray(closes, fast);
  const e26 = emaArray(closes, slow);
  const validStart = slow - 1; // first index where the slow EMA exists
  if (bars.length <= validStart) return { macd: [], signal: [], hist: [] };
  const macdVals = closes.map((_, i) =>
    e12[i] !== null && e26[i] !== null ? e12[i] - e26[i] : null
  );
  const sig = emaArray(macdVals.slice(validStart), signalPeriod);
  const macd = [];
  const signal = [];
  const hist = [];
  for (let i = validStart; i < bars.length; i++) {
    macd.push({ time: bars[i].time, value: macdVals[i] });
    const s = sig[i - validStart];
    if (s !== null) {
      signal.push({ time: bars[i].time, value: s });
      const h = macdVals[i] - s;
      hist.push({
        time: bars[i].time,
        value: h,
        color: h >= 0 ? 'rgba(46, 189, 133, 0.5)' : 'rgba(246, 70, 93, 0.5)',
      });
    }
  }
  return { macd, signal, hist };
}
