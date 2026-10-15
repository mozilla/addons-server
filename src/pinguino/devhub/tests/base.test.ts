import { describe, expect, it } from 'vitest';
import { resolveMount, toViteBasePath } from '../src/base';

describe('resolveMount', () => {
  it('resolves the unprefixed mount', () => {
    expect(resolveMount('/developers/')).toEqual({
      base: '/developers',
      locale: null,
    });
    expect(resolveMount('/developers/addon/x')).toEqual({
      base: '/developers',
      locale: null,
    });
  });

  it('captures a locale prefix', () => {
    expect(resolveMount('/en-US/developers/')).toEqual({
      base: '/en-US/developers',
      locale: 'en-US',
    });
    expect(resolveMount('/fr/developers/addon/x')).toEqual({
      base: '/fr/developers',
      locale: 'fr',
    });
  });

  it('falls back for paths outside the SPA', () => {
    expect(resolveMount('/')).toEqual({ base: '/developers', locale: null });
    expect(resolveMount('/en-US/firefox/addon/x')).toEqual({
      base: '/developers',
      locale: null,
    });
  });

  it('does not match a longer word starting with the segment', () => {
    expect(resolveMount('/developersblog')).toEqual({
      base: '/developers',
      locale: null,
    });
  });
});

describe('toViteBasePath', () => {
  it('strips a locale prefix to the unprefixed base', () => {
    expect(toViteBasePath('/en-US/developers/src/main.ts')).toBe(
      '/developers/src/main.ts',
    );
  });

  it('leaves an unprefixed path unchanged', () => {
    expect(toViteBasePath('/developers/@vite/client')).toBe(
      '/developers/@vite/client',
    );
  });

  it('preserves query strings', () => {
    expect(toViteBasePath('/fr/developers/src/main.ts?t=1')).toBe(
      '/developers/src/main.ts?t=1',
    );
  });
});
