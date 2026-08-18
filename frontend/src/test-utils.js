/**
 * Minimal React render helper for component tests.
 *
 * Deliberately not @testing-library/react. React 19 exports `act` itself, so
 * mounting a component into jsdom is `createRoot` plus `act` — about a dozen
 * lines — and the library would add three dependencies and sixty packages to
 * wrap them. If component tests ever need queries beyond `querySelector`, that
 * is the moment to reconsider, not before.
 *
 * Files using this must opt into a DOM with a docblock, because the project's
 * default vitest environment is `node` and the pure-module suites are faster for
 * staying there:
 *
 *     /** @vitest-environment jsdom *\/
 */
import { act } from 'react';
import { createRoot } from 'react-dom/client';

// React refuses to run `act` without this, and warns loudly rather than failing.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/** Mount `element`; returns the container plus rerender/unmount, both act-wrapped. */
export function render(element) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(element));
  return {
    container,
    rerender: (next) => act(() => root.render(next)),
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

/** Click a node inside act, so state updates flush before the next assertion. */
export function click(node) {
  act(() => {
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

/**
 * Let pending promises settle inside act.
 *
 * Needed by any component that fetches on mount: `render` returns with the
 * effect fired but its promise unresolved, so the first assertion would see the
 * loading state. Awaiting an empty async act flushes the microtask queue and the
 * re-render it causes, without React warning about an update outside act.
 */
export const flush = () => act(async () => {});
