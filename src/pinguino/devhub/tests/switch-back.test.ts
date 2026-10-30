import { describe, expect, it } from 'vitest';
import {
  pickSwitchBackPath,
  recordLanding,
  switchBackPath,
} from '../src/switch-back';

describe('pickSwitchBackPath', () => {
  it('returns the current url before a landing is recorded', () => {
    expect(pickSwitchBackPath('/initial', null, '/current')).toBe('/current');
  });

  it('returns the original incoming url while still on the landing page', () => {
    expect(
      pickSwitchBackPath('/developers/themes', '/developers', '/developers'),
    ).toBe('/developers/themes');
  });

  it('returns the current url once navigated away from the landing', () => {
    expect(
      pickSwitchBackPath(
        '/developers/themes',
        '/developers',
        '/developers/addon/x/edit',
      ),
    ).toBe('/developers/addon/x/edit');
  });
});

describe('switchBackPath', () => {
  it('uses the current url after navigating away from the landing', () => {
    history.pushState({}, '', '/developers/addon/x/edit');
    recordLanding();
    history.pushState({}, '', '/developers/addon/y/versions');
    expect(switchBackPath()).toBe('/developers/addon/y/versions');
  });

  it('does not return the landing url while still on it (offers the initial)', () => {
    history.pushState({}, '', '/developers/themes');
    recordLanding();
    // current === landing, so it returns the import-time initial url, which is
    // not the themes url we navigated to.
    expect(switchBackPath()).not.toBe('/developers/themes');
  });
});
