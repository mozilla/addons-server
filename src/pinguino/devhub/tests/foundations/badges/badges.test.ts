import { describe, expect, it } from 'vitest';
import type { DistributionBadge } from '../../../src/foundations/badges/distribution-badge';
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
    expect(label(invisibleRoot)).toBe('Hidden');
    expect(
      visibleRoot.querySelector('moz-status-badge')?.getAttribute('icon-start'),
    ).not.toBe(
      invisibleRoot
        .querySelector('moz-status-badge')
        ?.getAttribute('icon-start'),
    );
    expect(visibleRoot.querySelector('button')).toBeNull();
  });

  it('becomes a popover toggle when given slotted content', async () => {
    const el = document.createElement('visibility-badge') as VisibilityBadge;
    el.append(document.createElement('moz-radio-group'));
    document.body.append(el);
    await el.updateComplete;
    const root = el.shadowRoot as ShadowRoot;
    expect(root.querySelector('.chevron')).not.toBeNull();
    expect(label(root)).toBe('Visible');
    expect(root.querySelector('button')?.getAttribute('popovertarget')).toBe(
      root.querySelector('[popover] slot')?.parentElement?.id,
    );
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
