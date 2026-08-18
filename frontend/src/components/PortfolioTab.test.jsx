/**
 * @vitest-environment jsdom
 *
 * The frontend half of a crash that already shipped.
 *
 * `backend/tests/test_portfolio.py` pins the producer side and says why it
 * exists: a cost basis of exactly zero yields a real `unrealized_pnl` beside a
 * null `unrealized_pnl_pct`, and this component read the percentage off the
 * absolute figure's guard. The `TypeError` landed inside render, so the
 * ErrorBoundary unmounted the whole tab — including the form needed to correct
 * the position — leaving no route back from the UI.
 *
 * That backend test pins "which fields can be null, and when". Nothing pinned
 * the consumer, which is the half that actually threw. These do.
 *
 * The mock rows mirror `main.position_values` exactly, case for case, rather
 * than inventing shapes: price 250 / shares 10 / cost 0 is the same input the
 * backend test uses for the crash case.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import PortfolioTab from './PortfolioTab';
import { render, flush } from '../test-utils';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../api', () => ({
  get,
  post: vi.fn(),
  del: vi.fn(),
  patch: vi.fn(),
}));

/** One row, defaulted to an ordinary priced holding. */
const row = (over = {}) => ({
  ticker: 'AAPL',
  shares: 10,
  cost_basis: 200.0,
  note: null,
  currency: 'USD',
  price: 250.0,
  market_value: 2500.0,
  cost_value: 2000.0,
  unrealized_pnl: 500.0,
  unrealized_pnl_pct: 25.0,
  weight_pct: 100.0,
  score: null,
  tier: null,
  classification: null,
  score_as_of: null,
  quote_error: null,
  ...over,
});

const payload = (rows, over = {}) => ({
  rows,
  totals: {
    market_value: 2500.0,
    cost_value: 2000.0,
    unrealized_pnl: 500.0,
    unrealized_pnl_pct: 25.0,
    holdings: rows.length,
    watchlist_only: 0,
    ...(over.totals ?? {}),
  },
  concentration: { top_weight_pct: 100.0, top3_weight_pct: 100.0, hhi: 1.0 },
});

async function mount(data) {
  get.mockResolvedValue(data);
  const r = render(<PortfolioTab />);
  await flush();
  return r;
}

/** The P&L cell is the 7th column. */
const pnlCell = (container) => container.querySelector('tbody tr')?.children[6];

beforeEach(() => {
  get.mockReset();
});

describe('the P&L pair', () => {
  it('renders a zero-cost position without throwing', async () => {
    // The crash input, identical to test_portfolio.py's:
    //   position_values(price=250.0, shares=10.0, cost=0.0)
    //     -> unrealized_pnl 2500.0, unrealized_pnl_pct None
    const { container, unmount } = await mount(payload([
      row({ cost_basis: 0.0, cost_value: 0.0, unrealized_pnl: 2500.0, unrealized_pnl_pct: null }),
    ]));

    const cell = pnlCell(container);
    expect(cell).not.toBeUndefined();
    // The absolute gain is real and must be shown. Compared on digits only:
    // `big` falls through to `num` below a million, and `num` uses
    // toLocaleString, so the grouping separator is the runner's locale, not a
    // fact about this component.
    expect(cell.textContent).not.toBe('—');
    expect(cell.textContent.replace(/\D/g, '')).toBe('2500');
    // ...and the percentage is genuinely undefined, so no parenthesised return.
    expect(cell.textContent).not.toContain('(');
    expect(cell.textContent).not.toContain('%');
    unmount();
  });

  it('shows both figures for an ordinary position', async () => {
    const { container, unmount } = await mount(payload([row()]));
    expect(pnlCell(container).textContent).toBe('500 (+25.0%)');
    unmount();
  });

  it('renders an em dash, uncoloured, when there is no cost basis at all', async () => {
    // position_values(price=250.0, shares=10.0, cost=None) -> both null.
    const { container, unmount } = await mount(payload([
      row({ cost_basis: null, cost_value: null, unrealized_pnl: null, unrealized_pnl_pct: null }),
    ]));
    const cell = pnlCell(container);
    expect(cell.textContent).toBe('—');
    expect(cell.className).toBe('');
    unmount();
  });

  it('colours a loss down and a gain up', async () => {
    let view = await mount(payload([
      row({ unrealized_pnl: -300.0, unrealized_pnl_pct: -15.0 }),
    ]));
    expect(pnlCell(view.container).className).toBe('down');
    view.unmount();

    view = await mount(payload([row()]));
    expect(pnlCell(view.container).className).toBe('up');
    view.unmount();
  });
});

describe('the totals strip', () => {
  it('does not colour an unavailable total green', async () => {
    // `null >= 0` is true in JS, so the unguarded form rendered an unknown P&L
    // as a gain. The backend returns null here whenever total_cost is falsy,
    // which is any portfolio with no cost bases entered.
    const { container, unmount } = await mount(payload(
      [row({ cost_basis: null, cost_value: null, unrealized_pnl: null, unrealized_pnl_pct: null })],
      { totals: { unrealized_pnl: null, unrealized_pnl_pct: null, cost_value: null } },
    ));

    const totalPnl = container.querySelectorAll('.portfolio-totals .dcf-big')[1];
    expect(totalPnl.textContent).toBe('—');
    expect(totalPnl.className).not.toContain('up');
    expect(totalPnl.className).not.toContain('down');
    unmount();
  });
});

describe('the mixed-currency warning', () => {
  it('stays silent when the only other currency is a watchlist row', async () => {
    // It fired on a portfolio of five USD holdings because a watched HK name was
    // listed beneath them. A watchlist row has no market value, so it is in no
    // total, so it cannot make a total mixed.
    const { container, unmount } = await mount(payload([
      row(),
      row({
        ticker: '0700.HK', currency: 'HKD', shares: 0, market_value: null,
        cost_basis: null, cost_value: null, unrealized_pnl: null,
        unrealized_pnl_pct: null, weight_pct: null,
      }),
    ]));
    expect(container.textContent).not.toContain('totals add face values');
    unmount();
  });

  it('warns when two currencies really are being summed', async () => {
    const { container, unmount } = await mount(payload([
      row(),
      row({ ticker: '0700.HK', currency: 'HKD', market_value: 1000.0, weight_pct: 28.6 }),
    ]));
    expect(container.textContent).toContain('totals add face values');
    expect(container.textContent).toContain('USD, HKD');
    unmount();
  });
});
