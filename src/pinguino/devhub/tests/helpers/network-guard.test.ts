import { describe, expect, it } from 'vitest';
import { stubRequests } from './fixture';
import { takeUnmockedRequests } from './network-guard';

// Each test takes what it recorded, or tests/setup.ts would fail it.
describe('network guard', () => {
  it('rejects and records an unmocked request', async () => {
    await expect(fetch('/api/v5/nope/')).rejects.toThrow(
      'Unmocked fetch: /api/v5/nope/',
    );
    expect(takeUnmockedRequests()).toEqual(['/api/v5/nope/']);
  });

  it('lets stubRequests answer its paths and guards the rest', async () => {
    stubRequests({ '/api/v5/known/': { ok: true } });

    const res = await fetch('/api/v5/known/?lang=en-US');
    expect(await res.json()).toEqual({ ok: true });
    await expect(fetch('/api/v5/unknown/')).rejects.toThrow();
    expect(takeUnmockedRequests()).toEqual(['/api/v5/unknown/']);
  });
});
