/**
 * The contract these tests exist for: every formatter here answers "missing" and
 * "zero" differently, and a renderer that conflates them is wrong on screen
 * rather than crashing. The backend already learned this the expensive way — see
 * `position_values` in backend/main.py, extracted from its endpoint precisely so
 * a null contract could be pinned by a test, "which is why the crash shipped".
 * These are the frontend's equivalent, and nothing reached them until now.
 *
 * Deliberately locale-independent. `num` and `big` fall through to
 * `toLocaleString`, so any assertion on a thousands separator or a decimal mark
 * passes on a zh-HK dev machine and is a coin toss on a CI runner's locale. The
 * `digits` parameter is pinned by counting digit *characters* instead, which no
 * locale changes; the suffix logic uses `toFixed` and is locale-free already.
 */
import { describe, it, expect } from 'vitest';
import { num, big, pct, scoreColor, TIER_COLORS, PILLARS } from './format';

/** Digit characters only — separators and marks are not digits in any locale. */
const digitCount = (s) => (s.match(/[0-9]/g) ?? []).length;

describe('num', () => {
  it('renders missing as an em dash', () => {
    expect(num(null)).toBe('—');
    expect(num(undefined)).toBe('—');
  });

  it('renders zero as zero, not as missing', () => {
    // The falsy trap. A zero cost basis, a zero dividend and a zero score are
    // all real measurements; `—` would claim the data was never reported.
    expect(num(0)).toBe('0');
  });

  it('renders a non-finite number as missing, not as locale-dependent text', () => {
    // `Number(NaN).toLocaleString()` is not the string "NaN" everywhere: on the
    // zh-HK machine this was found on it is 非數值, on an en-US runner it is
    // NaN, and the suite runs on three OSes. A calculation that failed means
    // the same thing to a reader as a figure that was never reported.
    expect(num(NaN)).toBe('—');
    expect(num(Infinity)).toBe('—');
    expect(num(-Infinity)).toBe('—');
  });

  it('passes `digits` through to the formatter', () => {
    expect(digitCount(num(3.14159, 2))).toBe(3); // 3.14
    expect(digitCount(num(3.14159, 4))).toBe(5); // 3.1416
    expect(digitCount(num(3.14159, 0))).toBe(1); // 3
  });
});

describe('big', () => {
  it('renders missing as an em dash', () => {
    expect(big(null)).toBe('—');
    expect(big(undefined)).toBe('—');
  });

  it('renders zero as zero, not as missing', () => {
    expect(big(0)).toBe('0');
  });

  it('renders a non-finite number as missing rather than suffixing it', () => {
    // `Math.abs(Infinity) >= 1e12` is true, so the trillion branch fired and
    // `(Infinity / 1e12).toFixed(2) + 'T'` produced the string "InfinityT".
    expect(big(NaN)).toBe('—');
    expect(big(Infinity)).toBe('—');
    expect(big(-Infinity)).toBe('—');
  });

  it('picks the suffix at each threshold', () => {
    expect(big(1e12)).toBe('1.00T');
    expect(big(1e9)).toBe('1.00B');
    expect(big(1e6)).toBe('1.00M');
  });

  it('leaves anything below a million unsuffixed', () => {
    // Asserted as "no suffix" rather than as a literal, because the fallback is
    // `num` and therefore carries a locale-dependent separator.
    expect(big(999999)).not.toMatch(/[MBT]$/);
  });

  it('scales a negative on its magnitude and keeps the sign', () => {
    // `Math.abs` picks the threshold but the division keeps the sign — an
    // unrealised loss of -2.5bn must not fall through to the unsuffixed branch.
    expect(big(-2.5e9)).toBe('-2.50B');
  });
});

describe('pct', () => {
  it('renders missing as an em dash', () => {
    expect(pct(null)).toBe('—');
    expect(pct(undefined)).toBe('—');
  });

  it('renders zero as zero percent, not as missing', () => {
    expect(pct(0)).toBe('0.0%');
  });

  it('renders a non-finite number as missing', () => {
    // `pct` uses `toFixed`, so this one is locale-free and was rendering the
    // literal "NaN%" and "Infinity%".
    expect(pct(NaN)).toBe('—');
    expect(pct(Infinity)).toBe('—');
    expect(pct(-Infinity)).toBe('—');
  });

  it('converts a fraction to a percentage', () => {
    expect(pct(0.1234)).toBe('12.3%');
    expect(pct(-0.05, 2)).toBe('-5.00%');
  });
});

describe('scoreColor', () => {
  it('renders missing as the muted colour', () => {
    expect(scoreColor(null)).toBe('var(--muted)');
    expect(scoreColor(undefined)).toBe('var(--muted)');
  });

  it('bands on the boundaries inclusively', () => {
    // 65 and 50 are the same floors `scoring.TIERS` uses for A and B. A score
    // sitting exactly on a boundary belongs to the higher band.
    expect(scoreColor(65)).toBe('var(--up)');
    expect(scoreColor(64.9)).toBe('var(--gold)');
    expect(scoreColor(50)).toBe('var(--gold)');
    expect(scoreColor(49.9)).toBe('var(--down)');
  });

  it('bands a zero score rather than treating it as missing', () => {
    expect(scoreColor(0)).toBe('var(--down)');
  });

  it('mutes a non-finite score rather than banding it as the worst tier', () => {
    // `NaN >= 65` and `NaN >= 50` are both false, so a score that could not be
    // computed fell through to `--down` and rendered as one that scored
    // terribly — the exact conflation the docstring at the top of this file
    // says these formatters exist to prevent.
    expect(scoreColor(NaN)).toBe('var(--muted)');
    expect(scoreColor(Infinity)).toBe('var(--muted)');
    expect(scoreColor(-Infinity)).toBe('var(--muted)');
  });
});

describe('constants mirrored from the backend', () => {
  it('covers every tier the scoring engine can emit', () => {
    // Mirrors `scoring.TIERS`. A tier with no colour renders an undefined
    // background, which is a blank badge rather than a visible failure.
    expect(Object.keys(TIER_COLORS).sort()).toEqual(['A', 'B', 'C', 'D', 'S']);
  });

  it('lists the pillars in the order the scoring engine emits them', () => {
    // Mirrors `store.PILLARS`. Order is load-bearing: the scorecard renders
    // these positionally.
    expect(PILLARS).toEqual(['valuation', 'quality', 'health', 'growth', 'momentum']);
  });
});
