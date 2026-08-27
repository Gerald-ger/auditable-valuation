/**
 * @vitest-environment jsdom
 *
 * The tab with the most ways to be handed a hole, and no test until now.
 *
 * `App.test.jsx` mocks this component out rather than rendering it, so nothing
 * exercised it at all — including in demo mode, where it is one of only two tabs
 * that answer in full and therefore half of everything a visitor sees.
 *
 * What these pin is the *blast radius* of a missing number, not the arithmetic.
 * `financial_models.py` returns `{"error": ...}` and nothing else for three real
 * conditions — no positive free cash flow, no market cap, and WACC at or below
 * terminal growth — and `RIVN.json` and `O.json` are committed precisely because
 * they hit the first two. A single unguarded `dcf.assumptions.beta` on that
 * shape throws inside render, and `ErrorBoundary` then unmounts the whole tab.
 * That is the failure `PortfolioTab.test.jsx` exists to prevent a repeat of; the
 * guards here are the same shape and were equally untested.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import ModelsTab from './ModelsTab';
import { render, flush } from '../test-utils';

/**
 * `get` and `post` only. This component's import line is
 * `import { get, post } from '../api'` — supplying `del` or `stream` as well
 * would be surface for functions it never calls, and a double that does not
 * match its module is how a missing method throws unhandled inside a listener
 * while the run still reports a pass.
 */
const { get, post } = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({})),
  post: vi.fn(() => Promise.resolve({})),
}));

vi.mock('../api', () => ({ get, post }));

/**
 * The `dcf` block, defaulted to an ordinary valuation that ran.
 *
 * `over` is spread first and the two nested objects merged after it, so an
 * override of one assumption keeps the rest. Written the other way round the
 * trailing spread silently replaces the whole merged `assumptions`, which is how
 * the first draft handed the component a `beta_source` of undefined.
 */
const DCF_BASE = {
  assumptions: {
    base_fcf: 9.0e10, fcf_source: 'cash_flow_statement', fcf_period: '2023-09-30',
    growth_rate_year1: 0.08, growth_source: 'analyst_consensus_fwd',
    terminal_growth: 0.025, terminal_growth_source: 'platform_default',
    tax_rate: 0.21, projection_years: 10,
    risk_free_rate: 0.043, risk_free_source: 'us_treasury_10y',
    beta: 1.15, beta_source: 'computed',
    equity_risk_premium: 0.0431, equity_risk_premium_source: 'damodaran_2026_01',
    cost_of_equity: 0.0925, wacc_used: 0.0905, weight_equity: 0.97,
    currency: 'USD', reporting_currency: 'USD', fx_basis: 'single_currency',
  },
  enterprise_value: 3.2e12, net_debt: -5.0e10, equity_value: 3.25e12,
  fair_value_per_share: 210.5, current_price: 227.5, upside_pct: -7.4,
  diagnostics: { net_debt_assumed_zero: [] },
  // Both grids, populated. `dcf_valuation` has four return paths -- three
  // `{"error": ...}` dicts and one full result -- and the full one always
  // carries these, so `null` here would be a shape the backend cannot send.
  // The first draft used null and crashed the render; the crash was the mock's
  // fault, not the component's, and the component is right to rely on it.
  sensitivity: {
    terminal_growth_cols: [0.02, 0.0225, 0.025, 0.0275, 0.03],
    rows: [0.0805, 0.0855, 0.0905, 0.0955, 0.1005].map((wacc) => ({
      wacc,
      // A cell is null wherever that WACC/growth pair is non-viable (w <= g).
      values: [190.1, 198.2, 205.0, 212.4, null],
    })),
  },
  growth_sensitivity: {
    growth_rates: [0.04, 0.06, 0.08, 0.1, 0.12],
    values: [190.2, 198.1, 210.5, 224.0, 240.1],
  },
};

const dcf = (over = {}) => ({
  ...DCF_BASE,
  ...over,
  assumptions: { ...DCF_BASE.assumptions, ...(over.assumptions ?? {}) },
  diagnostics: { ...DCF_BASE.diagnostics, ...(over.diagnostics ?? {}) },
});

/** `/stock/{t}/analysis`, shaped as `financial_models.full_analysis` returns it. */
const analysis = (over = {}) => ({
  ticker: 'AAPL',
  company: {
    longName: 'Apple Inc.', sector: 'Technology', industry: 'Consumer Electronics',
    currency: 'USD', marketCap: 3.5e12,
  },
  // All six groups with every key, read out of `full_analysis` on the committed
  // AAPL fixture rather than guessed. A partial `ratios` is not a shape the
  // backend can send -- the first draft omitted `dupont` and the render threw on
  // `ratios.dupont.asset_turnover`, which is the mock being wrong, not the tab.
  ratios: {
    liquidity: { current_ratio: 0.98, quick_ratio: 0.9 },
    solvency: {
      debt_to_equity: 1.45, interest_coverage: 28.5,
      interest_coverage_period: '2023-09-30', net_debt: -5.0e10,
    },
    profitability: {
      gross_margin: 0.46, operating_margin: 0.31, net_margin: 0.25, roa: 0.28, roe: 1.6,
    },
    market: {
      pe_trailing: 30, pe_forward: 27, price_to_book: 45, ev_to_ebitda: 22,
      ev_to_revenue: 8, peg_ratio: 2.1, dividend_yield: 0.005,
    },
    dupont: {
      net_margin: 0.25, asset_turnover: 1.1, equity_multiplier: 5.7, roe_composed: 1.57,
    },
    growth: { revenue_growth: 0.08, earnings_growth: 0.12 },
  },
  dcf: dcf(),
  revenue_trend: [
    { period: '2022-09-24', revenue: 3.943e11 },
    { period: '2023-09-30', revenue: 3.833e11 },
  ],
  ...over,
});

/** A scorecard, only as much of one as this tab reads off it. */
const card = (over = {}) => ({
  classification: 'general', dcf_applicable: true,
  pillars: {
    valuation: { score: 55, metrics: { pe_trailing: { raw: 30, score: 50 } } },
    quality: { score: 82, metrics: { roe: { raw: 1.6, score: 70 } } },
  },
  ...over,
});

/** Route by path, the way the component's two independent fetches arrive. */
function route({ analysisBody = analysis(), scoreBody = card(), reject = null }) {
  get.mockImplementation((path) => {
    if (reject && path.includes(reject)) return Promise.reject(new Error('boom'));
    if (path.includes('/analysis')) return Promise.resolve(analysisBody);
    if (path.startsWith('/score/')) return Promise.resolve(scoreBody);
    return Promise.resolve({});
  });
}

async function mount(opts = {}) {
  route(opts);
  const r = render(<ModelsTab ticker="AAPL" />);
  await flush();
  return r;
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  post.mockResolvedValue({});
});

describe('ModelsTab', () => {
  it('contains a refused DCF to its own panel, and renders the rest of the tab', async () => {
    // The exact string financial_models.py returns when there is no positive FCF.
    const message = 'No positive free cash flow available for a DCF.';
    const { container } = await mount({
      analysisBody: analysis({ dcf: { error: message } }),
    });

    expect(container.querySelector('.error-banner')?.textContent).toBe(message);

    // The blast radius is the assertion. A DCF that could not run must cost the
    // DCF panel and nothing else — the company header and the ratio tables are
    // computed from `ratios`, which arrived intact.
    expect(container.querySelector('.company-header')).not.toBeNull();
    expect(container.querySelector('.ratio-grid')).not.toBeNull();

    // And no figure from the absent valuation leaked out as a blank or a zero.
    expect(container.querySelector('.dcf-result')).toBeNull();
  });

  it('leaves an unavailable upside uncoloured rather than green', async () => {
    // `upside_pct` is null whenever fx_basis is 'rate_unavailable': the model ran,
    // but its answer is in a currency the price cannot be compared against.
    // `null >= 0` is true in JS, so the naive ternary paints it as a gain.
    const { container } = await mount({
      analysisBody: analysis({
        dcf: dcf({
          upside_pct: null,
          assumptions: { fx_basis: 'rate_unavailable', currency: 'HKD' },
        }),
      }),
    });

    const upside = [...container.querySelectorAll('.dcf-big')]
      .find((el) => el.textContent.includes('%'));
    expect(upside).toBeDefined();
    expect(upside.className).not.toMatch(/\b(up|down)\b/);
  });

  it('keeps the tab when the scorecard fetch fails, since it is the enhancement', async () => {
    // The two fetches are independent on purpose: the quality bars beside each
    // ratio come from /score, and the component's own comment says a failure
    // there "must not blank the tab". Nothing pinned that it still does not.
    //
    // What catches a regression here is the run's exit code, not these
    // assertions. Measured: deleting the `.catch` leaves all four tests passing
    // and the summary reading "4 passed", while vitest exits 1 with "caught 1
    // unhandled error". The assertions below confirm the tab is intact; mounting
    // it against a rejecting fetch is what surfaces the rejection at all.
    const { container } = await mount({ reject: '/score/' });

    expect(container.querySelector('.error-banner')).toBeNull();
    expect(container.querySelector('.ratio-grid')).not.toBeNull();
  });

  it('draws no NaN into the revenue chart when there is one period, or none', async () => {
    // `Math.min(...[])` is Infinity, and a one-point line has no span to divide
    // by. Both reach the SVG as coordinate strings rather than as an exception,
    // so only the rendered attribute shows the difference.
    const one = await mount({
      analysisBody: analysis({ revenue_trend: [{ period: '2023-09-30', revenue: 3.8e11 }] }),
    });
    const points = one.container.querySelector('.rev-spark polyline')?.getAttribute('points');
    expect(points ?? '').not.toMatch(/NaN|Infinity/);
    one.unmount();

    const none = await mount({ analysisBody: analysis({ revenue_trend: [] }) });
    expect(none.container.querySelector('.rev-spark')).toBeNull();
    expect(none.container.textContent).toContain('No revenue history available.');
  });
});
