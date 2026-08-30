/**
 * @vitest-environment jsdom
 *
 * The other tab a demo visitor sees, and the other one nothing exercised.
 *
 * `App.test.jsx` mocks this component out, so until now the only coverage of
 * the scorecard was of the engine that produces the numbers, never of the thing
 * that draws them. The two are not the same risk: `scoring.py` is pinned by
 * golden tests and cannot silently change a score, while this file has one
 * guard — `verdict()`'s `if (!scored.length) return null` — standing between a
 * low-coverage card, which `scoring.py` produces deliberately, and reading
 * `.score` off `undefined` inside render. `ErrorBoundary` would then unmount
 * the tab, which is the shape of failure `PortfolioTab.test.jsx` exists for.
 *
 * Every mock shape below was read out of the running engine in demo mode
 * (`main._score_and_record`, `main.comps_endpoint`, `main.score_history`)
 * rather than written from the component's point of view, so these test the
 * payloads the backend can actually send.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import ScorecardTab from './ScorecardTab';
import { TIER_COLORS } from '../format';
import { render, flush } from '../test-utils';

/**
 * `get`, `post` and `stream` — this component's import line exactly. `stream`
 * has to be a function that invokes its callback rather than a bare promise, or
 * the narrative path would silently no-op; nothing here calls it, but a double
 * that cannot behave like its module is how the next test to try quietly passes.
 */
const { get, post, stream } = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({})),
  post: vi.fn(() => Promise.resolve({})),
  stream: vi.fn(async (path, body, onEvent) => { onEvent?.({ delta: '' }); }),
}));

vi.mock('../api', () => ({ get, post, stream }));

// Its own component with its own stream, and nothing here is about the debate.
vi.mock('./Debate', () => ({ default: () => null }));

/** A pillar, defaulted to one that counts toward the composite. */
const pillar = (over = {}) => ({
  score: 70, weight: 0.2, available_fraction: 1.0, insufficient: false,
  metrics: { roe: { raw: 1.6, score: 70 } },
  ...over,
});

/** `/score/{t}`, keys as `_score_and_record` returns them. */
const card = (over = {}) => ({
  ticker: 'AAPL', as_of: '2026-08-27T12:00:00+00:00', data_as_of: null,
  classification: 'general', dcf_applicable: true,
  composite_score: 65, tier: 'A', tier_label: 'Solid',
  confidence: 'HIGH', coverage_pct: 100,
  pillars: {
    valuation: pillar({ score: 22, weight: 0.2 }),
    quality: pillar({ score: 82, weight: 0.25 }),
    health: pillar({ score: 78, weight: 0.1 }),
    growth: pillar({ score: 67, weight: 0.3 }),
    momentum: pillar({ score: 79, weight: 0.15 }),
  },
  analyst_context: { target_mean: 324.01, analysts: 41, upside: 0.0418, recommendation: 'buy' },
  flags: [], missing_metrics: [], forensics: null,
  caveat: 'This score is a snapshot of current fundamentals.',
  ...over,
});

/** `/stock/{t}/comps`, keys as `comps_endpoint` returns them. */
const comps = (over = {}) => ({
  classification: 'general', dcf_applicable: true, current_price: 311.0,
  target: { ticker: 'AAPL', name: 'Apple Inc.' }, peers: [], failed_tickers: [], peers_used: 1,
  peer_medians: {}, peer_medians_n: {}, peer_operating_margin: null,
  implied_values: {}, implied_range: null, suppressed_multiples: {},
  football_field: [
    { method: 'DCF (sensitivity 25th–75th + growth)', low: 104.48, high: 142.84, mid: 122.26 },
    { method: 'Analyst targets', low: 215.0, high: 400.0, mid: 324.01, context_only: true },
  ],
  triangulation: null,
  ...over,
});

const history = (rows = []) => ({ ticker: 'AAPL', history: rows });

function route({ scoreBody = card(), compsBody = comps(), reject = null } = {}) {
  get.mockImplementation((path) => {
    if (reject && path.includes(reject)) return Promise.reject(new Error('boom'));
    if (path.includes('/history')) return Promise.resolve(history());
    if (path.includes('/peers')) return Promise.resolve({ suggested: [] });
    if (path.includes('/comps')) return Promise.resolve(compsBody);
    if (path.startsWith('/score/')) return Promise.resolve(scoreBody);
    return Promise.resolve({});
  });
}

async function mount(opts) {
  route(opts);
  const r = render(<ScorecardTab ticker="AAPL" aiOnline={false} />);
  await flush();
  await flush();   // comps is fetched after the first pair resolves
  return r;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  post.mockResolvedValue({});
});

describe('ScorecardTab', () => {
  it('colours the verdict edge by tier rather than by decoration', async () => {
    // The left edge used to be a fixed accent blue: the thickest left border in
    // the stylesheet and the only one carrying no information, while its
    // neighbours on this same tab use that edge for meaning. It now repeats the
    // tier the badge above states, from the same TIER_COLORS map.
    // jsdom normalises an inline hex to `rgb(...)`, so the expectation is
    // converted rather than the actual — comparing a hex against a hex here
    // would pass on a stylesheet that never applied it.
    const rgb = (hex) => `rgb(${[1, 3, 5]
      .map((i) => parseInt(hex.slice(i, i + 2), 16))
      .join(', ')})`;
    const shown = async (tier) => {
      const { container } = await mount({ scoreBody: card({ tier }) });
      return container.querySelector('.verdict').style.borderLeftColor;
    };

    // Distinct tiers must give distinct edges, or the border is still decoration
    // wearing a tier's name. The first draft of this test passed `score:` where
    // the route helper reads `scoreBody:`, so every case silently fell back to
    // the default card's A and the two colours were the same one — caught only
    // because the equality assertion below failed rather than matched.
    const top = await shown('S');
    const bottom = await shown('D');
    expect(top).not.toBe(bottom);
    expect(top).toBe(rgb(TIER_COLORS.S));
    expect(bottom).toBe(rgb(TIER_COLORS.D));

    // A is #3b82f6, which is --accent, so the change is a no-op on an A. Pinned
    // because that is the reason this was safe to ship, not a coincidence.
    expect(await shown('A')).toBe(rgb('#3b82f6'));

    // No tier to report falls back to the neutral border, never to a colour
    // that would assert a grade the card does not have.
    expect(await shown(null)).toBe('var(--border)');
  });

  it('survives a card where no pillar is scored, instead of throwing past the guard', async () => {
    // scoring.py produces this deliberately for a ticker whose coverage is too
    // thin: every pillar `insufficient`, so `verdict()`'s `scored` array is
    // empty. Without its early return, `scored[0]` is undefined and `best.score`
    // throws inside render — taking the whole tab down through ErrorBoundary.
    const thin = Object.fromEntries(
      ['valuation', 'quality', 'health', 'growth', 'momentum'].map((k) =>
        [k, pillar({ score: null, insufficient: true, available_fraction: 0 })]),
    );
    const { container } = await mount({
      scoreBody: card({
        pillars: thin, composite_score: null, tier: null, tier_label: null,
        confidence: 'LOW', coverage_pct: 0,
      }),
    });

    // Rendered at all — the assertion that matters.
    expect(container.querySelector('.score-big')).not.toBeNull();
    // And the verdict withheld rather than composed from nothing.
    expect(container.querySelector('.panel.verdict')).toBeNull();
  });

  it('shows a scored-but-excluded pillar as excluded, not as a bar', async () => {
    // A pillar under 40% metric coverage carries a real score and contributes
    // nothing. Branching on `score === null` alone drew it full width, so it
    // could read 97 beside a composite it had no part in.
    const { container } = await mount({
      scoreBody: card({
        pillars: {
          ...card().pillars,
          momentum: pillar({ score: 97, insufficient: true, available_fraction: 0.2 }),
        },
      }),
    });

    const excluded = [...container.querySelectorAll('.pillar-row')]
      .find((row) => row.textContent.toLowerCase().includes('momentum'));
    expect(excluded).toBeDefined();
    expect(excluded.querySelector('.pillar-fill')).toBeNull();
    expect(excluded.querySelector('.pillar-missing')?.textContent)
      .toContain('excluded from the composite');
    // The number is still shown, so the reader can see what was left out.
    expect(excluded.querySelector('.pillar-score.excluded')?.textContent).toBe('97');
  });

  it('keeps the tab when the score-history fetch fails', async () => {
    // History is fetched separately and its rejection is swallowed on purpose.
    //
    // What catches a regression here is the run's exit code, not these
    // assertions. Measured: deleting the `.catch` leaves all four tests passing
    // and the summary reading "4 passed", while vitest exits 1 with "caught 1
    // unhandled error". The assertions below confirm the tab is intact; mounting
    // it against a rejecting fetch is what surfaces the rejection at all.
    const { container } = await mount({ reject: '/history' });

    expect(container.querySelector('.error-banner')).toBeNull();
    expect(container.querySelector('.score-big')).not.toBeNull();
    expect(container.querySelectorAll('.pillar-row').length).toBe(5);
  });

  it('names a method it cannot apply, rather than dropping it', async () => {
    // A bank or REIT gets `not_applicable` on the DCF row. The chart's own
    // early return only fires when `ranges` is empty, and this one is not — it
    // holds a row that cannot be drawn, which has to be accounted for in words
    // or it looks like the method was never tried.
    //
    // An earlier draft of this test also asserted no `NaN` reached any style
    // attribute, on the theory that an empty domain makes `Math.min(...[])`
    // Infinity and every coordinate NaN. It does — but nothing calls the scale
    // in that state: the overlap band is behind `t?.overlap`, the price rule
    // behind `currentPrice`, and the bars behind `drawn.map`. Forcing the scale
    // to return NaN outright left all four tests passing, which is how the
    // assertion was found to be unfalsifiable, and it was dropped rather than
    // kept as decoration.
    const { container } = await mount({
      compsBody: comps({
        current_price: null,
        triangulation: null,
        football_field: [{
          method: 'DCF (sensitivity 25th–75th + growth)', not_applicable: true,
          reason: 'Banks are valued on equity, not enterprise value.',
        }],
      }),
    });

    expect(container.querySelector('.ff-skipped')?.textContent)
      .toContain('Banks are valued on equity');
    expect(container.querySelector('.ff-bar')).toBeNull();
  });

  it('draws no axis when no row survives to set its scale', async () => {
    // The abandoned assertion described in the test above was right about the
    // cause and wrong about the reach. `Math.min(...[])` is Infinity and
    // `Math.max(...[])` is -Infinity, so on this same fixture `min` is
    // Infinity, `max` is -Infinity and their midpoint is NaN. The three guards
    // that test lists — `t?.overlap`, `currentPrice`, `drawn.map` — all protect
    // callers of `x()`. The axis ticks do not call `x()`; they read `min` and
    // `max` directly, and the axis row itself is a sibling of the `.map`, gated
    // only by the empty-`ranges` early return. So those three values reached
    // the DOM as visible text.
    //
    // Asserted on the element rather than on the text it held, because
    // `num(NaN)` is locale-dependent — 非數值 here, "NaN" on a US runner — and
    // this suite runs on three operating systems.
    const { container } = await mount({
      compsBody: comps({
        current_price: null,
        triangulation: null,
        football_field: [{
          method: 'DCF (sensitivity 25th–75th + growth)', not_applicable: true,
          reason: 'Banks are valued on equity, not enterprise value.',
        }],
      }),
    });

    expect(container.querySelector('.ff-axis')).toBeNull();
  });

  it('names the two methods that actually disagreed, rather than assuming a DCF', async () => {
    // The note under a LOW verdict used to read "A discounted cash flow and
    // trading comps measure different things". That was safe while a DCF was
    // the only intrinsic model — a bank could not reach a conviction verdict at
    // all, because peer multiples were the only method that scored and one
    // method is not a triangulation. Since 2026-08-29 a bank gets an excess
    // return bar, so the sentence became reachable for a company whose
    // triangulation contains no DCF at all.
    const { container } = await mount({
      compsBody: comps({
        classification: 'financials_bank',
        dcf_applicable: false,
        football_field: [
          { method: 'DCF', not_applicable: true, reason: 'Does not apply to a financials bank.' },
          { method: 'Excess return (ROE x cost of equity, 25th-75th)', low: 285, high: 385, mid: 331 },
          { method: 'Peer multiples (implied)', low: 240, high: 260, mid: 250 },
        ],
        triangulation: {
          conviction: 'LOW', midpoint_spread: 0.32, diverged: true,
          methods_scored: ['Excess return (ROE x cost of equity, 25th-75th)',
                           'Peer multiples (implied)'],
          anchors: {
            low_method: 'Peer multiples (implied)', low_mid: 250,
            high_method: 'Excess return (ROE x cost of equity, 25th-75th)', high_mid: 331,
          },
        },
      }),
    });

    const note = container.querySelector('.muted-note')?.textContent ?? '';
    expect(note).toContain('measure different things');
    expect(note).toContain('Excess return');
    expect(note).toContain('Peer multiples');
    // The claim that would have been false for this company.
    expect(note).not.toContain('discounted cash flow');
  });
});
