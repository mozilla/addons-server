import 'urlpattern-polyfill';

import { Router } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BASE } from '../../../../src/base';
import * as api from '../../../../src/data/api';
import { ADDON_STATUS } from '../../../../src/data/statuses';
import type {
  Addon,
  AddonDistribution,
  FileUpload,
  Version,
} from '../../../../src/data/types';
import '../../../../src/pages/addon/main';
import { DEFAULT_VERSION, mount, settle } from '../../../helpers/fixture';

vi.mock('../../../../src/data/api');

@customElement('test-addon-router')
class TestRouter extends LitElement {
  router = new Router(this, [
    {
      path: `${BASE}/addon/*`,
      render: () => html`<addon-routes></addon-routes>`,
    },
  ]);

  render() {
    return this.router.outlet();
  }
}

const ADDON: Addon = {
  slug: 'tab-organizer',
  name: 'Tab Organizer',
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.incomplete,
  version: '—',
  lastUpdated: '',
  visibility: 'visible',
  canChangeVisibility: false,
  screenshots: [],
};

const THEME: Addon = {
  ...ADDON,
  slug: 'night-sky',
  name: 'Night Sky',
  kind: 'theme',
  icon: 'themes',
  previewUrl: 'https://example.com/previews/night-sky.png',
};

const makeVersion = (channel: AddonDistribution): Version => ({
  ...DEFAULT_VERSION,
  id: 7,
  version: '1.0.0',
  channel,
  file: {
    id: 1,
    url: 'https://example.com/files/tab-organizer.xpi',
    size: 1,
    status: 'unreviewed',
  },
});

const makeUpload = (channel: AddonDistribution): FileUpload => ({
  uuid: crypto.randomUUID(),
  channel,
  manifest_data: {
    name: { 'en-US': 'Tab Organizer' },
    summary: { 'en-US': 'Organize tabs' },
    homepage: { 'en-US': 'https://example.com/tab-organizer' },
  },
  processed: true,
  submitted: false,
  url: '',
  valid: true,
  validation: null,
  version: '1.0.0',
});

const link = (path: string) => `${BASE}/addon/${path}`;

const actualApi = await vi.importActual<typeof api>('../../../../src/data/api');

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.localized).mockImplementation(actualApi.localized);
  vi.mocked(api.fetchAgreement).mockResolvedValue({
    display_name: 'Dev',
    has_read_developer_agreement: true,
    last_developer_agreement_change: '2026-01-01',
  });
  vi.mocked(api.postUpload).mockImplementation(async (_, channel) =>
    makeUpload(channel),
  );
  vi.mocked(api.fetchUpload).mockImplementation(
    () => vi.mocked(api.postUpload).mock.results.at(-1)?.value,
  );
  vi.mocked(api.postAddon).mockImplementation(async () => ({
    addon: ADDON,
    version: makeVersion(
      vi.mocked(api.postUpload).mock.calls.at(-1)?.[1] ?? 'listed',
    ),
  }));
  vi.mocked(api.fetchAddons).mockResolvedValue([ADDON]);
  vi.mocked(api.fetchEulaPolicy).mockResolvedValue({
    eula: '',
    privacyPolicy: '',
  });
  vi.mocked(api.fetchCategories).mockResolvedValue([
    { slug: 'tabs', name: 'Tabs', type: 'extension' },
    { slug: 'nature', name: 'Nature', type: 'statictheme' },
  ]);
});

async function mountFlow(path: string) {
  window.history.replaceState({}, '', link(path));
  const host = await mount<TestRouter>('test-addon-router');
  await host.router.goto(link(path));
  await settle(host);
  return ui(host);
}

function ui(host: TestRouter) {
  const shadow = (el: Element | null | undefined) =>
    el?.shadowRoot as ShadowRoot;
  const root = () => {
    const routes = shadow(host.shadowRoot?.querySelector('addon-routes'));
    const submit = shadow(routes?.querySelector('submit-routes'));
    return shadow(submit?.querySelector('addon-submission'));
  };
  const step = (tag: string) => shadow(root()?.querySelector(`.outlet ${tag}`));
  return {
    root,
    step,
    listing: () =>
      shadow(step('submit-listing')?.querySelector('listing-details-card')),
    continue: () =>
      root()?.querySelector<HTMLElement>(
        '.continue moz-button[variant="default"]',
      ),
    submit: () =>
      root()?.querySelector<HTMLElement>('moz-page-header moz-button'),
    stepCount: () => root()?.querySelector('.step-count')?.textContent,
  };
}

type UI = ReturnType<typeof ui>;

const enabled = (el: HTMLElement | null | undefined) =>
  Boolean(el) && !el?.hasAttribute('disabled');

const at = (path: string) =>
  expect.poll(() => location.pathname).toBe(link(path));

function pick(picker: Element | null | undefined, value: string) {
  if (!picker) throw new Error('expected a picker in the DOM');
  Object.assign(picker, { value });
  picker.dispatchEvent(new Event('change'));
}

async function continueOn($: UI) {
  await expect.poll(() => enabled($.continue())).toBe(true);
  $.continue()?.click();
}

async function uploadValid($: UI) {
  const fileInput = () =>
    $.step('submit-upload')?.querySelector('moz-input-file');
  await expect.poll(fileInput).toBeTruthy();
  const input = fileInput();
  Object.assign(input as Element, {
    files: [new File(['xpi'], 'tab-organizer.xpi')],
  });
  input?.dispatchEvent(new Event('change'));
  await continueOn($);
}

async function noSource($: UI) {
  await expect.poll(() => $.step('submit-source')).toBeTruthy();
  pick(
    $.step('submit-source').querySelectorAll('moz-visual-picker')[1],
    'false',
  );
  await continueOn($);
}

const listingValue = ($: UI, label: string) =>
  (
    [
      ...($.listing()?.querySelectorAll(
        '.form moz-input-text, .form moz-textarea',
      ) ?? []),
    ].find((i) => i.getAttribute('label') === label) as
      | HTMLInputElement
      | undefined
  )?.value;

async function fillListing($: UI, category: string, license: string) {
  const box = () =>
    [...($.listing()?.querySelectorAll('.cat-grid moz-checkbox') ?? [])].find(
      (b) => b.getAttribute('label') === category,
    ) as HTMLInputElement | undefined;
  const licenses = () =>
    $.listing()
      ?.querySelector('license-field')
      ?.shadowRoot?.querySelector('moz-radio-group');
  await expect.poll(() => box() && licenses()).toBeTruthy();
  const checkbox = box() as HTMLInputElement;
  checkbox.checked = true;
  checkbox.dispatchEvent(new Event('change'));
  pick(licenses(), license);
  await continueOn($);
}

async function submit($: UI) {
  await expect.poll(() => enabled($.submit())).toBe(true);
  const notes = $.step('review-submit').querySelector('#reviewer-notes');
  if (notes) Object.assign(notes, { value: '' });
  $.submit()?.click();
}

const lastUpload = async () =>
  (await vi.mocked(api.postUpload).mock.results.at(-1)?.value) as FileUpload;

describe('addon-submission', () => {
  it('submits a listed add-on, creating it from its listing details', async () => {
    const $ = await mountFlow('submit/distribution');
    await continueOn($);

    await at('submit/upload-listed');
    await uploadValid($);
    await at('submit/source-listed');
    await noSource($);

    await at('submit/details');
    expect(api.postAddon).not.toHaveBeenCalled();
    // Filled in from the upload manifest.
    await expect
      .poll(() => listingValue($, 'Add-on name'))
      .toBe('Tab Organizer');
    expect(listingValue($, 'Summary')).toBe('Organize tabs');
    expect(listingValue($, 'Homepage of the add-on')).toBe(
      'https://example.com/tab-organizer',
    );
    expect(
      $.listing().querySelector<HTMLInputElement>('.url-slug')?.value,
    ).toBe('tab-organizer');
    await fillListing($, 'Tabs', 'MPL-2.0');

    await at('tab-organizer/submit/graphics');
    expect(api.postAddon).toHaveBeenCalledWith({
      categories: ['tabs'],
      version: { upload: (await lastUpload()).uuid, license: 'MPL-2.0' },
    });
    await continueOn($);

    await at('tab-organizer/submit/review');
    await submit($);
    await at('tab-organizer/submit/finish');
  });

  it('creates an unlisted add-on from its upload and skips the listing', async () => {
    const $ = await mountFlow('submit/upload-unlisted');
    await uploadValid($);

    await at('tab-organizer/submit/source-unlisted');
    expect(api.postAddon).toHaveBeenCalledWith({
      version: { upload: (await lastUpload()).uuid },
    });
    await noSource($);

    await at('tab-organizer/submit/review');
    await submit($);
    await at('tab-organizer/submit/finish');
  });

  it('submits an enterprise add-on with no source or listing steps', async () => {
    const $ = await mountFlow('submit/upload-enterprise');
    await uploadValid($);

    await at('tab-organizer/submit/review');
    await submit($);
    await at('tab-organizer/submit/finish');
  });
});

describe('addon-submission of a theme', () => {
  beforeEach(() => {
    vi.mocked(api.postAddon).mockImplementation(async () => ({
      addon: THEME,
      version: makeVersion('listed'),
    }));
    vi.mocked(api.fetchAddons).mockResolvedValue([THEME]);
  });

  it('submits a listed theme, with no source or images steps', async () => {
    const $ = await mountFlow('submit/theme/distribution');
    await expect
      .poll(() =>
        $.root()?.querySelector('moz-page-header')?.getAttribute('heading'),
      )
      .toBe('Submit theme');
    await continueOn($);

    await at('submit/theme/upload-listed');
    await uploadValid($);

    await at('submit/theme/details');
    await fillListing($, 'Nature', 'CC-BY-4.0');

    await at('night-sky/submit/review');
    expect(api.postAddon).toHaveBeenCalledWith({
      categories: ['nature'],
      version: { upload: (await lastUpload()).uuid, license: 'CC-BY-4.0' },
    });
    await submit($);
    await at('night-sky/submit/finish');
  });
});
