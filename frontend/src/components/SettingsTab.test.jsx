/**
 * @vitest-environment jsdom
 *
 * The tab that takes a credential, which is the only surface in this app that
 * does. Two of these tests are about what it must *not* do.
 *
 * The four states it distinguishes are the feature: "no key", "a key that has
 * not been used", "a key that works", and "a key that does not". Collapsing the
 * last two is the failure the whole 2026-08-28 line of work set out to remove —
 * hand-editing the JSON told you nothing, and a tab that only said "saved" would
 * tell you exactly as little.
 */
import { act } from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import SettingsTab from './SettingsTab';
import { render, click, flush } from '../test-utils';

/** `get`, `post`, `del` — this component's import line exactly. */
const { get, post, del } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  del: vi.fn(),
}));

vi.mock('../api', () => ({ get, post, del }));

async function mount(fmp) {
  get.mockResolvedValue({ status: 'ok', fmp });
  const r = render(<SettingsTab />);
  await flush();
  return r;
}

/** React tracks its own value on the node, so a bare assignment is ignored. */
async function type(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value').set;
  await act(async () => {
    setter.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

const verdict = (c) => c.querySelector('.fmp-verdict');
const field = (c) => c.querySelector('input');
const saveButton = (c) => [...c.querySelectorAll('button')]
  .find((b) => b.textContent.includes('Save'));
const removeButton = (c) => [...c.querySelectorAll('button')]
  .find((b) => b.textContent.includes('Remove'));

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  del.mockReset();
});

describe('SettingsTab', () => {
  it('separates a key that is set from a key that works', async () => {
    // The distinction the whole feature exists for. Both are `configured: true`.
    const working = await mount({ configured: true, last_call: 'ok' });
    expect(verdict(working.container).textContent).toMatch(/set and working/i);
    expect(verdict(working.container).className).not.toMatch(/bad/);
    working.unmount();

    const broken = await mount({ configured: true, last_call: 'failed' });
    expect(verdict(broken.container).textContent).toMatch(/failed/i);
    expect(verdict(broken.container).className).toMatch(/bad/);
  });

  it('does not call an absent key a problem', async () => {
    // No key is the documented default and the keyless tier covers it, so this
    // screen has to read as "fine", not as something to fix.
    const { container } = await mount({ configured: false, last_call: null });
    expect(verdict(container).textContent).toMatch(/No key set/i);
    expect(verdict(container).className).not.toMatch(/bad/);
    expect(verdict(container).textContent).toMatch(/That works/i);
    // Nothing to remove.
    expect(removeButton(container)).toBeUndefined();
  });

  it('says a rejected key changed nothing, and keeps it in the box to fix', async () => {
    // The sentence that had to exist after 2026-08-28. "Your key is failing" and
    // "what you just typed was refused and nothing moved" are different facts,
    // and the first version could only say the former.
    const { container } = await mount({ configured: true, last_call: 'ok' });
    post.mockResolvedValue({ configured: true, last_call: 'ok', saved: false });

    await type(field(container), 'a-wrong-key');
    click(saveButton(container));
    await flush();

    expect(post).toHaveBeenCalledWith('/settings/fmp-key', { key: 'a-wrong-key' });
    expect(container.querySelector('.error-banner')?.textContent)
      .toMatch(/nothing was changed/i);
    // The stored key's own verdict is untouched: it was never retested.
    expect(verdict(container).textContent).toMatch(/set and working/i);
    // And the paste stays put, because a rejected key is usually a mistyped one.
    expect(field(container).value).toBe('a-wrong-key');
  });

  it('clears the box only when the key was actually stored', async () => {
    const { container } = await mount({ configured: false, last_call: null });
    post.mockResolvedValue({ configured: true, last_call: 'ok', saved: true });

    await type(field(container), 'a-good-key');
    click(saveButton(container));
    await flush();

    expect(field(container).value).toBe('');
    expect(container.querySelector('.error-banner')).toBeNull();
    expect(verdict(container).textContent).toMatch(/set and working/i);
  });

  it('keeps the key out of the DOM', async () => {
    // `type="password"` so it is not shoulder-readable, and cleared after the
    // save so it is not sitting in a form for the rest of the session. There is
    // no endpoint that returns a key, so nothing can put one back.
    const { container } = await mount({ configured: false, last_call: null });
    expect(field(container).type).toBe('password');

    post.mockResolvedValue({ configured: true, last_call: 'ok', saved: true });
    await type(field(container), 'sk-SECRET');
    click(saveButton(container));
    await flush();

    expect(field(container).value).toBe('');
    expect(container.innerHTML).not.toContain('sk-SECRET');
  });

  it('will not post an empty key', async () => {
    // The backend rejects it too; this stops the round trip.
    const { container } = await mount({ configured: true, last_call: 'ok' });
    expect(saveButton(container).disabled).toBe(true);

    await type(field(container), '   ');
    expect(saveButton(container).disabled).toBe(true);
  });

  it('shows what the backend said when a save is refused', async () => {
    // Demo mode answers 403 with a reason, and a silent failure here would be
    // the same defect this tab was built to remove.
    const { container } = await mount({ configured: false, last_call: null });
    post.mockRejectedValue(new Error('Demo mode uses committed fixtures'));

    await type(field(container), 'x');
    click(saveButton(container));
    await flush();

    expect(container.querySelector('.error-banner')?.textContent)
      .toContain('Demo mode');
  });

  it('removes a stored key through the delete path', async () => {
    const { container } = await mount({ configured: true, last_call: 'ok' });
    del.mockResolvedValue({ configured: false, last_call: null });

    click(removeButton(container));
    await flush();

    expect(del).toHaveBeenCalledWith('/settings/fmp-key');
    expect(verdict(container).textContent).toMatch(/No key set/i);
  });

  it('survives a backend too old to send the field', async () => {
    const { container } = await mount(undefined);
    expect(verdict(container).textContent).toMatch(/No key set/i);
  });
});
