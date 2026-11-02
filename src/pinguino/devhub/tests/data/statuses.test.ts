import { describe, expect, it } from 'vitest';
import {
  ADDON_STATUS,
  canChangeVisibility,
  resolveAddonStatus,
  resolveVersionStatus,
  resolveVisibility,
  VERSION_STATUS,
  VISIBILITY,
} from '../../src/data/statuses';

describe('resolveAddonStatus', () => {
  it('maps each documented add-on status', () => {
    expect(resolveAddonStatus('public')).toBe(ADDON_STATUS.public);
    expect(resolveAddonStatus('nominated')).toBe(ADDON_STATUS.nominated);
    expect(resolveAddonStatus('incomplete')).toBe(ADDON_STATUS.incomplete);
    expect(resolveAddonStatus('rejected')).toBe(ADDON_STATUS.rejected);
    expect(resolveAddonStatus('disabled')).toBe(ADDON_STATUS.disabled);
    expect(resolveAddonStatus('deleted')).toBe(ADDON_STATUS.deleted);
  });

  it('falls back for a missing or unrecognised status', () => {
    expect(resolveAddonStatus(undefined).label).toBe('Unknown');
    // File-only spelling; never valid for an add-on.
    expect(resolveAddonStatus('unreviewed').label).toBe('Unknown');
  });
});

describe('resolveVersionStatus', () => {
  it('maps the non-ambiguous statuses', () => {
    expect(resolveVersionStatus('public')).toBe(VERSION_STATUS.public);
    expect(resolveVersionStatus('unreviewed')).toBe(VERSION_STATUS.unreviewed);
    expect(resolveVersionStatus(undefined).label).toBe('Unknown');
  });

  it('splits "disabled" into the three states it collapses', () => {
    expect(resolveVersionStatus('disabled', { isDisabled: true }).label).toBe(
      'Disabled by you',
    );
    expect(
      resolveVersionStatus('disabled', { reviewed: '2025-08-18T00:00:00Z' })
        .label,
    ).toBe('Rejected');
    // Never reviewed by a human: disabled, but not a rejection.
    expect(resolveVersionStatus('disabled', { reviewed: null })).toBe(
      VERSION_STATUS.unreviewed,
    );
  });

  it('prefers the author disable over the review outcome', () => {
    expect(
      resolveVersionStatus('disabled', {
        isDisabled: true,
        reviewed: '2025-08-18T00:00:00Z',
      }).label,
    ).toBe('Disabled by you');
  });
});

describe('visibility', () => {
  it('reads straight off is_disabled', () => {
    expect(resolveVisibility(false)).toBe('visible');
    expect(resolveVisibility(true)).toBe('invisible');
    expect(VISIBILITY.visible.label).toBe('Visible');
    expect(VISIBILITY.invisible.label).toBe('Hidden');
  });

  it('locks the control once Mozilla disabled or deleted the add-on', () => {
    expect(canChangeVisibility('public')).toBe(true);
    expect(canChangeVisibility('nominated')).toBe(true);
    expect(canChangeVisibility('disabled')).toBe(false);
    expect(canChangeVisibility('deleted')).toBe(false);
  });
});
