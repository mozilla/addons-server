import { describe, expect, it } from 'vitest';
import type { ComingSoon } from '../../src/components/coming-soon';
import '../../src/components/coming-soon';
import { mount } from '../helpers/fixture';

describe('coming-soon', () => {
  it('points at the shared switch-back link so the feature stays reachable', async () => {
    const el = await mount<ComingSoon>('coming-soon');
    expect(
      (el.shadowRoot as ShadowRoot).querySelector('switch-back-link'),
    ).not.toBeNull();
  });
});
