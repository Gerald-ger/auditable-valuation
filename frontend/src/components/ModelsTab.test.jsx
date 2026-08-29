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

/**
 * The two intrinsic models a DCF cannot replace, read out of `full_analysis` on
 * the committed fixtures rather than guessed — JPM through
 * `excess_returns_valuation` with its market bars, O through
 * `dividend_discount_valuation` without them.
 *
 * Without bars for O deliberately. With them its beta regresses to 0.4263 and
 * the model refuses, which is what production serves and what REFUSED_DDM below
 * pins. That leaves the *valued* dividend branch unreachable from any committed
 * fixture, so it would ship rendered by nothing — which is the whole reason this
 * shape is written out here.
 */
const EXCESS_RETURN = {
  book_value_of_equity: 342393000000.0, excess_return_pv: 218866798790.29,
  terminal_value_pv: 317325754526.54, equity_value: 878585553316.83,
  fair_value_per_share: 330.52, current_price: 359.24, upside_pct: -8.0,
  assumptions: {
    currency: 'USD', reporting_currency: 'USD', stage1_years: 1, stage2_years: 9,
    cost_of_equity_used: 0.0877, cost_of_equity_source: 'capm',
    terminal_growth: 0.025, terminal_growth_source: 'platform_default',
    fx_basis: 'single_currency', fx_rate_used: null,
    roe: 0.1580465153533972, roe_periods: 4, roe_latest: 0.1626230676444904,
    retention_ratio: 0.6954317278912959, growth_rate_explicit: 0.10991056125941125,
  },
  diagnostics: {
    excess_spread: 0.070347, implied_terminal_payout: 0.841819, current_payout: 0.304568,
    price_to_book: 2.789, book_value_per_share: 128.81, tangible_share_of_book: 0.8117,
    fair_value_latest_roe: 346.32, terminal_value_share: 0.361178, terminal_value_high: false,
  },
  sensitivity: {
    roe_cols: [0.138047, 0.148047, 0.158047, 0.168047, 0.178047],
    rows: [
      { cost_of_equity: 0.0777, values: [325.43, 364.49, 405.59, 448.8, 494.2] },
      { cost_of_equity: 0.0827, values: [292.83, 327.86, 364.71, 403.44, 444.13] },
    ],
  },
};

const DIVIDEND_DISCOUNT = {
  dividend_per_share: 3.12738, dividend_pv: 25.9219, terminal_value_pv: 43.5857,
  fair_value_per_share: 69.51, current_price: 62.7, upside_pct: 10.9,
  assumptions: {
    currency: 'USD', reporting_currency: 'USD', stage1_years: 1, stage2_years: 9,
    cost_of_equity_used: 0.0751, cost_of_equity_source: 'capm',
    terminal_growth: 0.025, terminal_growth_source: 'platform_default',
    fx_basis: 'single_currency', fx_rate_used: null,
    growth_rate_explicit: 0.044256116949842994, growth_periods: 3,
    dividend_per_share: 3.12738, dividend_period: '2025-12-31',
  },
  diagnostics: {
    terminal_value_share: 0.627064, terminal_value_high: false,
    growth_mean_yoy: 0.044504, share_count_growth: 0.4145,
    cost_of_equity_headroom: 0.0021, cost_of_debt_pre_tax: 0.073,
    implied_cost_of_equity: 0.080481, trailing_dividend_yield: 0.049878,
    payout_of_ffo_proxy: [
      { period: '2024-12-31', payout_of_ffo_proxy: 0.8299 },
      { period: '2025-12-31', payout_of_ffo_proxy: 0.8153 },
    ],
  },
  sensitivity: {
    terminal_growth_cols: [0.02, 0.0225, 0.025, 0.0275, 0.03],
    rows: [
      { cost_of_equity: 0.0651, values: [78.63, 82.57, 87.01, 92.03, 97.76] },
      { cost_of_equity: 0.0701, values: [70.7, 73.82, 77.29, 81.16, 85.51] },
    ],
  },
  growth_sensitivity: {
    growth_rates: [0.014256, 0.029256, 0.044256, 0.059256, 0.074256],
    values: [61.08, 65.17, 69.51, 74.1, 78.97],
  },
};

/** What production actually serves for O: the model declines to price it. */
const REFUSED_DDM = {
  error: "Cost of equity (6.20%) is below this company's pre-tax cost of debt "
    + '(7.30%). A lender ranks ahead of a shareholder, so the discount rate this '
    + 'model would apply to every dividend is not one the company could raise '
    + 'equity at — no fair value is reported rather than one built on it.',
};

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

  it('leaves an unavailable intrinsic upside uncoloured rather than green', async () => {
    // `null >= 0` is true in JS, so the obvious expression paints a withheld
    // comparison green. The DCF panel already carries this guard and a test for
    // it; the new panel reproduced the guard and, until a mutation said so,
    // nothing here would have noticed if it were dropped.
    const { container } = await mount({
      analysisBody: analysis({
        excess_return: {
          ...EXCESS_RETURN,
          upside_pct: null,
          assumptions: { ...EXCESS_RETURN.assumptions, fx_basis: 'rate_unavailable' },
        },
      }),
    });
    const upside = [...container.querySelectorAll('.intrinsic-panel .dcf-big')]
      .find((el) => el.textContent.includes('%'));
    expect(upside).toBeTruthy();
    expect(upside.className).not.toMatch(/\b(up|down)\b/);
    // And the reason the comparison is missing is stated, not left blank.
    expect(container.querySelector('.intrinsic-panel').textContent).toContain(
      'withheld rather than made across two units',
    );
  });

  it('claims no conversion when the statements are already in the traded currency', async () => {
    // `reporting_currency` is always sent, so gating the footnote on its mere
    // presence would print "converted from USD at —" on every US company.
    // Caught by mutation only after the fixtures started carrying the field.
    const { container } = await mount({
      analysisBody: analysis({ excess_return: EXCESS_RETURN }),
    });
    const panel = container.querySelector('.intrinsic-panel');
    expect(panel.textContent).not.toContain('converted from');
    expect(panel.textContent).not.toContain('unit-free');
  });

  it('names the unit on a bridge whose figures were converted', async () => {
    // The one fx_basis no fixture exercised. The bridge figures are converted at
    // the output boundary — the excess return model did not do that until P5a
    // found it — so the footnote may only claim a conversion that happened, and
    // the unit has to be on screen beside the numbers rather than inferred.
    const { container } = await mount({
      analysisBody: analysis({
        excess_return: {
          ...EXCESS_RETURN,
          assumptions: {
            ...EXCESS_RETURN.assumptions,
            currency: 'HKD', reporting_currency: 'CNY',
            fx_basis: 'converted', fx_rate_used: 1.1,
          },
        },
      }),
    });
    const panel = container.querySelector('.intrinsic-panel');
    const titles = [...panel.querySelectorAll('.sens-title')].map((el) => el.textContent);
    expect(titles.some((t) => t.includes('HKD') && t.includes('aggregate'))).toBe(true);
    expect(panel.textContent).toContain('converted from CNY at 1.1');
    expect(panel.textContent).toContain('the ratios are unit-free and are not');
  });

  it('names the unit as per share for the dividend model', async () => {
    const { container } = await mount({
      analysisBody: analysis({ dividend_discount: DIVIDEND_DISCOUNT }),
    });
    const titles = [...container.querySelectorAll('.intrinsic-panel .sens-title')]
      .map((el) => el.textContent);
    expect(titles.some((t) => t.includes('USD per share'))).toBe(true);
    expect(titles.some((t) => t.includes('aggregate'))).toBe(false);
  });

  it('renders no intrinsic panel for a company whose DCF applies', async () => {
    // The AAPL shape: `full_analysis` gates both keys to null off their own
    // company type, and the mock leaves them undefined, which is the same
    // question asked a second way. Neither may produce a panel — an empty shell
    // above the DCF would read as a model that ran and found nothing.
    const { container } = await mount({});
    expect(container.querySelector('.intrinsic-panel')).toBeNull();
    expect(container.querySelector('.dcf-result')).not.toBeNull();
  });

  it('values a bank on excess return, above the DCF panel that cannot', async () => {
    const { container } = await mount({
      analysisBody: analysis({ excess_return: EXCESS_RETURN }),
      scoreBody: card({ classification: 'financials_bank', dcf_applicable: false }),
    });
    const panel = container.querySelector('.intrinsic-panel');
    expect(panel).not.toBeNull();
    expect(panel.textContent).toContain('Excess return');
    expect(panel.textContent).toContain('330.52');
    expect(panel.textContent).toContain('-8%');

    // Above, not below. The DCF panel carries the banner saying it does not
    // apply here, so meeting it first would answer the reader's question with
    // the model that has no answer.
    const panels = [...container.querySelectorAll('.panel')];
    expect(panels.indexOf(panel)).toBeLessThan(
      panels.findIndex((el) => el.querySelector('.dcf-controls')),
    );

    // Aggregate, and abbreviated as such — the other model's bridge is per share
    // and runs in tens, which is the contrast the shared formatter has to keep.
    expect(panel.textContent).toContain('342.39B');
    // The grid is the model's own axis, not the DCF's.
    expect(panel.querySelector('.sens-table thead').textContent).toContain('ROE');
    // ...and the one-dimensional ROE sweep is deliberately not drawn beside it:
    // it is the middle row of that grid, which is why comps declines to union it.
    expect(panel.querySelectorAll('.sens-table')).toHaveLength(1);
  });

  it('prices a REIT on its dividends, with the sweep the grid cannot reach', async () => {
    const { container } = await mount({
      analysisBody: analysis({ dividend_discount: DIVIDEND_DISCOUNT }),
      scoreBody: card({ classification: 'real_estate_reit', dcf_applicable: false }),
    });
    const panel = container.querySelector('.intrinsic-panel');
    expect(panel.textContent).toContain('Dividend discount');
    expect(panel.textContent).toContain('69.51');
    expect(panel.textContent).toContain('+10.9%');
    // Per share from the first line: the bridge starts at the declared dividend
    // and its period, not at an aggregate distribution.
    expect(panel.textContent).toContain('3.13');
    expect(panel.textContent).toContain('2025-12-31');

    // Two grids here and one for the bank, and the asymmetry is the point.
    expect(panel.querySelectorAll('.sens-table')).toHaveLength(2);
    expect(panel.textContent).toContain('dividend growth rate');
  });

  it('colours each grid cell against the price, not against itself', async () => {
    // The grid's only visual claim: which assumptions put fair value above what
    // the market charges. Painting every cell one colour left all 196 tests
    // green — found by mutation, so the discrimination is asserted here rather
    // than assumed from the class names existing.
    const { container } = await mount({
      analysisBody: analysis({ excess_return: EXCESS_RETURN }),
    });
    const firstRow = container.querySelectorAll('.intrinsic-panel .sens-table tbody tr')[0];
    const cells = [...firstRow.querySelectorAll('td')].slice(1);

    // 325.43 sits below the 359.24 price and the other four above it.
    expect(cells.map((c) => c.className)).toEqual([
      'cell-down', 'cell-up', 'cell-up', 'cell-up', 'cell-up',
    ]);
    expect(cells[0].textContent).toBe('325.43');
  });

  it('shows a refusal as the answer rather than an empty panel', async () => {
    const { container } = await mount({
      analysisBody: analysis({ dividend_discount: REFUSED_DDM }),
      scoreBody: card({ classification: 'real_estate_reit', dcf_applicable: false }),
    });
    const panel = container.querySelector('.intrinsic-panel');
    expect(panel).not.toBeNull();
    expect(panel.querySelector('.notice-banner').textContent).toContain(
      'below this company',
    );
    // Nothing that would need `assumptions` to exist. An `{"error": ...}` dict
    // has no other key, and a single unguarded read of one throws inside render
    // and takes the whole tab down with it — the failure this file exists for.
    expect(panel.querySelector('.dcf-result')).toBeNull();
    expect(panel.querySelector('.sens-table')).toBeNull();
  });

  it('labels the intrinsic figures in the currency the model reports', async () => {
    // The company header says HKD; the model says USD. Printing an unlabelled
    // number under a header in the other unit is the bug the DCF panel already
    // carries a comment about.
    const { container } = await mount({
      analysisBody: analysis({
        company: { longName: 'X', sector: 'S', industry: 'I', currency: 'HKD', marketCap: 1e9 },
        excess_return: EXCESS_RETURN,
      }),
    });
    const labels = [...container.querySelectorAll('.intrinsic-panel .dcf-label')]
      .map((el) => el.textContent);
    expect(labels).toContain('Fair value / share USD');
    expect(labels).toContain('Current price USD');
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
