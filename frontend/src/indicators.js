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
