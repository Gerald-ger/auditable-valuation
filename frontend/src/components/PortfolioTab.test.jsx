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
import { act } from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import PortfolioTab from './PortfolioTab';
import { render, flush } from '../test-utils';

/**
 * All three return promises in `../api`, and so do these.
 *
 * `patch` used to be here too and is gone: this component imports only
 * `del, get, post`, so it was mock surface for a function that is never called.
 *
 * The promise floor is not what the CI failures of 2026-08-20 were about — those
 * were `patch(...).catch()` on an undefined in PriceChart, and this component
 * `await`s instead, which tolerates undefined perfectly well. Measured: the
 * write-flow tests below pass against bare `vi.fn()` doubles. It is here so that
 * a switch to `.then()` chaining fails for the product's reasons rather than the
 * double's — see the mutation note in CHANGELOG 2026-08-20 (e).
 */
const { get, post, del } = vi.hoisted(() => ({
  get: vi.fn(() => Promise.resolve({})),
  post: vi.fn(() => Promise.resolve({})),
  del: vi.fn(() => Promise.resolve({})),
}));

vi.mock('../api', () => ({ get, post, del }));

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
    // The two fields that say what unit these figures are in. `main.portfolio()`
    // converts every money figure to `BASE_CURRENCY` and names it here, or
    // withholds the totals and names the currencies it could not price.
    currency: 'HKD',
    unconverted_currencies: [],
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
  post.mockReset();
  del.mockReset();
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

describe('what unit the totals are in', () => {
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
    expect(container.textContent).not.toContain('Holdings span');
    unmount();
  });

  it('says the figures were converted, and to what', async () => {
    // This used to read "totals add face values without FX conversion, so the
    // aggregate is indicative only" — accurate when written and false now. A
    // warning that survives the defect it describes is worse than none.
    const { container, unmount } = await mount(payload([
      row(),
      row({ ticker: '0700.HK', currency: 'HKD', market_value: 1000.0, weight_pct: 28.6 }),
    ]));
    expect(container.textContent).toContain('USD, HKD');
    expect(container.textContent).toContain('converted to HKD');
    expect(container.textContent).not.toContain('without FX conversion');
    unmount();
  });

  it('labels the money columns with the unit they are actually in', async () => {
    const { container, unmount } = await mount(payload([row()]));
    const headers = [...container.querySelectorAll('thead th')].map((h) => h.textContent);
    expect(headers).toContain('Value (HKD)');
    expect(headers).toContain('P&L (HKD)');
    // Price and cost are per-share quotes in the holding's own market and are
    // deliberately not converted, so they must not claim a base-currency label.
    expect(headers).toContain('Price');
    expect(headers).toContain('Cost');
    unmount();
  });

  it('withholds the totals rather than adding across units when a rate is missing', async () => {
    // The refusal path. `fx_rate` returns None on an outage and the endpoint
    // then declines the sum — falling back to face values would be exactly the
    // old wrong number with a warning beside it.
    const { container, unmount } = await mount(payload(
      [row(), row({ ticker: '0700.HK', currency: 'HKD', market_value: 1000.0 })],
      { totals: { currency: null, unconverted_currencies: ['USD'],
                  market_value: null, cost_value: null,
                  unrealized_pnl: null, unrealized_pnl_pct: null } },
    ));

    expect(container.textContent).toContain('No exchange rate for USD');
    // Without a conversion the figures are each in their own currency, so the
    // column must not be labelled with one.
    const headers = [...container.querySelectorAll('thead th')].map((h) => h.textContent);
    expect(headers).toContain('Value');
    expect(headers).not.toContain('Value (HKD)');
    unmount();
  });
});

describe('the write flows', () => {
  /**
   * `save` and `remove` had no test at all, so `post` and `del` were mocked and
   * never called. That is what let their doubles sit at a bare `vi.fn()`
   * unnoticed; a double nothing invokes cannot be wrong in a way anything sees.
   */
  const setValue = (input, value) => {
    // React tracks the last value it wrote on the DOM node and skips onChange
    // when they match, so assigning `.value` directly is swallowed. Going
    // through the prototype setter is what makes a controlled input see it.
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
    act(() => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('posts the position the form describes, then reloads', async () => {
    const { container, unmount } = await mount(payload([row()]));
    get.mockClear();

    setValue(container.querySelector('.position-form input'), 'msft');
    await act(async () => {
      container.querySelector('.position-form')
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(post).toHaveBeenCalledWith('/portfolio/position', {
      ticker: 'MSFT', shares: 0, cost_basis: null, note: null,
    });
    expect(get).toHaveBeenCalledWith('/portfolio'); // the reload after the write
    unmount();
  });

  it('refuses to post an empty ticker', async () => {
    const { container, unmount } = await mount(payload([row()]));

    await act(async () => {
      container.querySelector('.position-form')
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(post).not.toHaveBeenCalled();
    unmount();
  });

  it('deletes the row that was clicked, then reloads', async () => {
    const { container, unmount } = await mount(payload([row()]));
    get.mockClear();

    await act(async () => {
      container.querySelector('.row-remove')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(del).toHaveBeenCalledWith('/portfolio/position/AAPL');
    expect(get).toHaveBeenCalledWith('/portfolio');
    unmount();
  });

  it('shows a failed write instead of swallowing it', async () => {
    // Both handlers catch and set `error`; without this nothing pinned that a
    // rejected write reaches the reader at all.
    const { container, unmount } = await mount(payload([row()]));
    post.mockRejectedValueOnce(new Error('ticker not found'));

    setValue(container.querySelector('.position-form input'), 'NOPE');
    await act(async () => {
      container.querySelector('.position-form')
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain('ticker not found');
    unmount();
  });
});
