import 'urlpattern-polyfill';
import type { LitElement } from 'lit';
import { describe, expect, it } from 'vitest';
import '../../../src/pages/addon/main';
import { mount, settle } from '../../helpers/fixture';

type RouterHost = LitElement & { _routes: { goto(p: string): Promise<void> } };

async function goto(tag: string, path: string) {
  const el = await mount<RouterHost>(tag);
  await el._routes.goto(path);
  await settle(el);
  return el.shadowRoot as ShadowRoot;
}

// Django retries a 404 without its trailing slash; the SPA is served for every
// path under /developers/, so a trailing slash reaches the client router and
// has to match there instead.
describe('addon-routes tolerates a trailing slash', () => {
  it.each([
    ['addon-slug/edit/', 'devhub-addon'],
    ['addon-slug/edit/authors/', 'devhub-addon'],
    ['addon-slug/feed/', 'devhub-addon'],
    ['validate/', 'coming-soon'],
    ['api/key/', 'coming-soon'],
  ])('%s renders %s', async (path, tag) => {
    const root = await goto('addon-routes', path);
    expect(root.querySelector(tag)).not.toBeNull();
    expect(root.querySelector('error-page')).toBeNull();
  });

  // The bare slug redirects to its edit tab, rendering nothing itself.
  it('redirects a bare slug with a trailing slash', async () => {
    const root = await goto('addon-routes', 'addon-slug/');
    expect(root.querySelector('error-page')).toBeNull();
    expect(root.querySelector('devhub-addon')).toBeNull();
  });

  it('carries the tab and section through', async () => {
    const root = await goto('addon-routes', 'addon-slug/edit/authors/');
    const page = root.querySelector('devhub-addon');
    expect(page?.tab).toBe('edit');
    expect(page?.section).toBe('authors');
  });
});
