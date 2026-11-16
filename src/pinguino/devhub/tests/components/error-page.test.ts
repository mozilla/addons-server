import { describe, expect, it } from 'vitest';
import type { ErrorPage } from '../../src/components/error-page';
import '../../src/components/error-page';
import { ApiError, errorStatus } from '../../src/data/http';
import { mount } from '../helpers/fixture';

async function page(props: Partial<ErrorPage> = {}) {
  const el = await mount<ErrorPage>('error-page', props);
  const root = el.shadowRoot as ShadowRoot;
  return {
    root,
    heading: root.querySelector('h1')?.textContent?.trim(),
    message: root.querySelector('p')?.textContent?.trim(),
    illustration: root.querySelector('moz-illustration')?.getAttribute('name'),
  };
}

describe('error-page', () => {
  it('is a 404 unless told otherwise', async () => {
    const { heading, illustration } = await page();
    expect(heading).toBe('404: Page not found');
    expect(illustration).toBe('kit-alert-tail-exclamation');
  });

  it('presents a known status with its own copy and artwork', async () => {
    const { heading, illustration } = await page({ code: 403 });
    expect(heading).toBe("403: You don't have access to this");
    expect(illustration).toBe('kit-hold-lock');
  });

  it('falls back to the family for an unmapped status', async () => {
    const server = await page({ code: 502 });
    expect(server.heading).toBe('502: Something went wrong on our end');
    expect(server.illustration).toBe('kit-plug-error');

    // A 4xx must not borrow the server-error copy — it blames the wrong side.
    const client = await page({ code: 429 });
    expect(client.heading).toBe("429: That request didn't work");
    expect(client.illustration).toBe('kit-alert-tail-exclamation');
  });

  it('lets a caller say something more specific', async () => {
    const { heading, message } = await page({
      code: 404,
      heading: 'No such version',
      message: 'That version was deleted.',
    });
    expect(heading).toBe('404: No such version');
    expect(message).toBe('That version was deleted.');
  });

  it('offers a way home, replaceable by the actions slot', async () => {
    const { root } = await page();
    const slot = root.querySelector<HTMLSlotElement>('slot[name="actions"]');
    expect(slot).not.toBeNull();
    // The fallback is the slot's own content, so it shows until a caller fills it.
    expect(slot?.querySelector('moz-button')?.getAttribute('href')).toBe(
      '/developers',
    );
  });
});

describe('errorStatus', () => {
  it('uses the status the API reported', () => {
    expect(errorStatus(new ApiError(403, 'nope'))).toBe(403);
  });

  it('treats anything that never reached the API as our fault', () => {
    expect(errorStatus(new TypeError('offline'))).toBe(500);
    expect(errorStatus('weird')).toBe(500);
  });
});
