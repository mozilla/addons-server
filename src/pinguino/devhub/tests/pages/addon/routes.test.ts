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
  it('renders the add-on page for a slug', async () => {
    const root = await goto('addon-routes', 'addon-slug');
    const page = root.querySelector('devhub-addon');
    expect(page).not.toBeNull();
    expect(page?.slug).toBe('addon-slug');
  });

  it('hands submit/* to the submit routes', async () => {
    const root = await goto('addon-routes', 'submit/agreement');
    expect(root.querySelector('submit-routes')).not.toBeNull();
  });
});

describe('submit-routes', () => {
  it('renders the agreement page', async () => {
    const root = await goto('submit-routes', 'agreement');
    const page = root.querySelector('devhub-agreement');
    expect(page).not.toBeNull();
  });
});
