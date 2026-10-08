import { describe, expect, it, vi } from 'vitest';

// The error/loading branches depend on the query controller's state, which the
// real queries never reach. Mock addonsQuery to a controller stuck
// in the error state so the error UI is reachable; the rest of the data barrel
// stays real.
const { refetchMock } = vi.hoisted(() => ({ refetchMock: vi.fn() }));

vi.mock('../../src/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/data')>();
  const controller = () => ({
    isError: true,
    isPending: false,
    data: undefined,
  });
  controller.refetch = refetchMock;
  return { ...actual, addonsQuery: () => controller };
});

import type { DevhubHome } from '../../src/pages/devhub-home';
import '../../src/pages/devhub-home';
import { mount } from '../helpers/fixture';

describe('devhub-home (error state)', () => {
  it('shows an error message and retries on click', async () => {
    const el = await mount<DevhubHome>('devhub-home');
    const root = el.shadowRoot as ShadowRoot;

    expect(root.textContent).toContain("We couldn't load your add-ons.");
    expect(root.querySelectorAll('addon-card')).toHaveLength(0);

    root
      .querySelector<HTMLElement>('moz-button')
      ?.dispatchEvent(new MouseEvent('click'));
    expect(refetchMock).toHaveBeenCalledOnce();
  });
});
