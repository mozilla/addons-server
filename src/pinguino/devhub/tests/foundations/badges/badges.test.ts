import { describe, expect, it } from 'vitest';
import type { DistributionBadge } from '../../../src/foundations/badges/distribution-badge';
import type { ListingStatusBadge } from '../../../src/foundations/badges/listing-status-badge';
import type { VisibilityBadge } from '../../../src/foundations/badges/visibility-badge';
import '../../../src/foundations/badges';
import { mount } from '../../helpers/fixture';

const label = (root: ShadowRoot) =>
  root.querySelector('moz-status-badge')?.textContent?.trim();

describe('visibility-badge', () => {
  it('labels each visibility and gives it a distinct icon', async () => {
    const visible = await mount<VisibilityBadge>('visibility-badge', {
      visibility: 'visible',
    });
    const invisible = await mount<VisibilityBadge>('visibility-badge', {
      visibility: 'invisible',
    });

    const visibleRoot = visible.shadowRoot as ShadowRoot;
    const invisibleRoot = invisible.shadowRoot as ShadowRoot;
    expect(label(visibleRoot)).toBe('Visible');
    expect(label(invisibleRoot)).toBe('Invisible');
    expect(
      visibleRoot.querySelector('moz-status-badge')?.getAttribute('icon-start'),
    ).not.toBe(
      invisibleRoot
        .querySelector('moz-status-badge')
        ?.getAttribute('icon-start'),
    );
  });
});

describe('listing-status-badge', () => {
  const badge = (type: string) =>
    mount<ListingStatusBadge>('listing-status-badge', {
      type: type as ListingStatusBadge['type'],
    });

  // One type drives the surface and the dot together, so they can't disagree.
  it('carries a dot of its own type for every status', async () => {
    for (const type of ['success', 'warning', 'critical', 'ghost', 'default']) {
      const root = (await badge(type)).shadowRoot as ShadowRoot;
      expect(root.querySelector('moz-status-dot')?.getAttribute('type')).toBe(
        type,
      );
    }
  });
});

describe('distribution-badge', () => {
  it('maps each channel to its label', async () => {
    for (const [distribution, expected] of [
      ['listed', 'AMO'],
      ['unlisted', 'Self'],
      ['enterprise', 'Enterprise'],
    ] as const) {
      const el = await mount<DistributionBadge>('distribution-badge', {
        distribution,
      });
      expect(label(el.shadowRoot as ShadowRoot)).toBe(expected);
    }
  });
});
