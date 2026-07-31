// Technical indicator math. All functions take chart bars ({time, close, ...})
// and return lightweight-charts-ready [{time, value}] arrays.

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

// MACD(12, 26, 9)
export function macdSeries(bars) {
  const closes = bars.map((b) => b.close);
  const e12 = emaArray(closes, 12);
  const e26 = emaArray(closes, 26);
  const validStart = 25; // first index where EMA26 exists
  if (bars.length <= validStart) return { macd: [], signal: [], hist: [] };
  const macdVals = closes.map((_, i) =>
    e12[i] !== null && e26[i] !== null ? e12[i] - e26[i] : null
  );
  const sig = emaArray(macdVals.slice(validStart), 9);
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
