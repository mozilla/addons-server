import 'urlpattern-polyfill';

import type { LitElement } from 'lit';
import { describe, expect, it } from 'vitest';
import '../../../src/pages/addon/main';
import { mount, settle } from '../../helpers/fixture';

type RouterHost = LitElement & {
  _routes: { goto(path: string): Promise<void> };
};

async function goto(tag: string, path: string) {
  const el = await mount<RouterHost>(tag);
  await el._routes.goto(path);
  await settle(el);
  return el.shadowRoot as ShadowRoot;
}

describe('addon-routes', () => {
  it('renders the add-on page for a slug/tab', async () => {
    const root = await goto('addon-routes', 'addon-slug/edit');
    const page = root.querySelector('devhub-addon');
    expect(page).not.toBeNull();
    expect(page?.slug).toBe('addon-slug');
    expect(page?.tab).toBe('edit');
  });

  it('redirects a bare slug to its edit tab', async () => {
    // The bare :slug route has an `enter` redirect and renders nothing itself.
    const root = await goto('addon-routes', 'addon-slug');
    expect(root.querySelector('devhub-addon')).toBeNull();
  });

  it('redirects ownership to the edit authors section', async () => {
    // The :slug/ownership route redirects via `enter` and renders nothing.
    const root = await goto('addon-routes', 'addon-slug/ownership');
    expect(root.querySelector('devhub-addon')).toBeNull();
  });

  it('carries the tab and the ?page= onto the add-on page', async () => {
    history.replaceState({}, '', '?page=4');
    const root = await goto('addon-routes', 'addon-slug/feed');
    const page = root.querySelector('devhub-addon');
    expect(page?.tab).toBe('feed');
    expect(page?.page).toBe(4);
    history.replaceState({}, '', location.pathname);
  });

  it('hands submit/* to the submit routes', async () => {
    const root = await goto('addon-routes', 'submit/agreement');
    expect(root.querySelector('submit-routes')).not.toBeNull();
  });

  it('stubs pages that are not reimplemented yet', async () => {
    const root = await goto('addon-routes', 'validate');
    expect(root.querySelector('coming-soon')).not.toBeNull();
  });

  it('shows the error page for a path no nested route claims', async () => {
    const root = await goto('addon-routes', 'slug/edit/section/extra');
    expect(root.querySelector('error-page')).not.toBeNull();
  });
});

describe('submit-routes', () => {
  it('renders the agreement page', async () => {
    const root = await goto('submit-routes', 'agreement');
    const page = root.querySelector('devhub-agreement');
    expect(page).not.toBeNull();
  });

  it('shows the error page for an unknown submit step', async () => {
    const root = await goto('submit-routes', 'bogus');
    expect(root.querySelector('error-page')).not.toBeNull();
  });

  // Two navigations on purpose: there has to be a previous match for a
  // fallback-less router to strand.
  it('replaces the previous page rather than stranding it', async () => {
    const el = await mount<RouterHost>('submit-routes');
    await el._routes.goto('agreement');
    await settle(el);
    expect(el.shadowRoot?.querySelector('devhub-agreement')).not.toBeNull();

    await el._routes.goto('bogus');
    await settle(el);
    expect(el.shadowRoot?.querySelector('devhub-agreement')).toBeNull();
    expect(el.shadowRoot?.querySelector('error-page')).not.toBeNull();
  });
});
