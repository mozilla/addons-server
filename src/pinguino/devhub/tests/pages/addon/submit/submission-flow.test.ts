import 'urlpattern-polyfill';

import { Router } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BASE } from '../../../../src/base';
import { queryClient, queryKeys } from '../../../../src/data';
import * as api from '../../../../src/data/api';
import { ADDON_STATUS } from '../../../../src/data/statuses';
import type {
  Addon,
  AddonDistribution,
  FileUpload,
  Version,
} from '../../../../src/data/types';
import type { SubmitListing } from '../../../../src/pages/addon/submit/templates/listing';
import '../../../../src/pages/addon/versions/submit/main';
import { DEFAULT_VERSION, mount, settle } from '../../../helpers/fixture';

vi.mock('../../../../src/data/api');

const SUBMIT = `${BASE}/addon/my-addon/versions/submit/`;

@customElement('test-router')
class TestRouter extends LitElement {
  router = new Router(this, [
    {
      path: `${SUBMIT}*`,
      render: () =>
        html`<version-submission slug="my-addon"></version-submission>`,
    },
    { path: '/*', render: () => html`` },
  ]);

  render() {
    return this.router.outlet();
  }
}

const VERSION: Version = {
  ...DEFAULT_VERSION,
  id: 20,
  file: {
    id: 20,
    url: 'https://example.com/files/addon.xpi',
    size: 0,
    status: 'public',
  },
};

const ADDON: Addon = {
  slug: 'my-addon',
  name: 'My add-on',
  kind: 'extension',
  icon: 'extension',
  status: ADDON_STATUS.public,
  version: '1.0.0',
  lastUpdated: '',
  visibility: 'visible',
  canChangeVisibility: true,
  channels: ['listed'],
  summary: 'Does things',
  categories: ['tabs'],
};

const makeUpload = (args: Partial<FileUpload> = {}): FileUpload => ({
  uuid: crypto.randomUUID(),
  channel: 'listed',
  manifest_data: null,
  processed: true,
  submitted: false,
  url: '',
  valid: true,
  validation: null,
  version: '1.0.0',
  ...args,
});

// The submit notice only reads the add-on's per-channel submissionNotice, so a
// slug + that map is enough; the rest of Addon is irrelevant here.
const makeAddon = (
  submissionNotice?: Partial<Record<AddonDistribution, string | null>>,
): Addon => ({ slug: 'my-addon', submissionNotice }) as unknown as Addon;

const BAD_VALIDATION = {
  valid: false,
  validation: {
    errors: 1,
    warnings: 0,
    notices: 0,
    messages: [{ type: 'error' as const, message: 'Bad validation error' }],
  },
};

beforeEach(() => {
  vi.resetAllMocks();
  // The flow now observes the profile (for the site-status submit notice).
  // Clear the cache so each test refetches, and default to a healthy status.
  queryClient.clear();
  vi.mocked(api.fetchProfile).mockResolvedValue({
    id: '1',
    name: 'Kate',
    siteStatus: { readOnly: false, siteNotice: null, submissionNotice: null },
  });
  // The flow also looks up the add-on for its per-channel submit notice.
  vi.mocked(api.fetchAddons).mockResolvedValue([]);
  vi.mocked(api.postUpload).mockResolvedValue(makeUpload());
  vi.mocked(api.fetchUpload).mockImplementation(
    () => vi.mocked(api.postUpload).mock.results.at(-1)?.value,
  );
  vi.mocked(api.fetchVersion).mockResolvedValue(VERSION);
  vi.mocked(api.postVersion).mockResolvedValue(VERSION);
  vi.mocked(api.patchVersion).mockResolvedValue(VERSION);
  vi.mocked(api.fetchAddons).mockResolvedValue([ADDON]);
  vi.mocked(api.fetchVersions).mockResolvedValue([VERSION]);
});

async function mountFlow(path: string) {
  window.history.replaceState({}, '', `${SUBMIT}${path}`);
  const host = await mount<TestRouter>('test-router');
  await host.router.goto(`${SUBMIT}${path}`);
  await settle(host);
  const el = host.shadowRoot?.querySelector('version-submission');
  if (!el) throw new Error('expected version-submission in the DOM');
  // Its steps wait for the add-on and its versions.
  await expect
    .poll(() => el.shadowRoot?.querySelector('.outlet > *'))
    .toBeTruthy();
  await settle(el);
  return ui(el);
}

function chooseFiles(input: Element | null, ...files: File[]) {
  if (!input) throw new Error('expected moz-input-file in the DOM');
  Object.assign(input, {
    files,
    clear: () => Object.assign(input, { files: [] }),
  });
  input.dispatchEvent(new Event('change'));
}

function pick(picker: Element | null, value: string) {
  if (!picker) throw new Error('expected moz-visual-picker in the DOM');
  Object.assign(picker, { value });
  picker.dispatchEvent(new Event('change'));
}

function ui(el: LitElement) {
  const root = el.shadowRoot as ShadowRoot;
  const step = (tag: string) =>
    root.querySelector(`.outlet ${tag}`)?.shadowRoot as ShadowRoot;
  const upload = () => step('submit-upload');
  return {
    root,
    step,
    upload,
    source: () => step('submit-source'),
    fileInput: () => upload().querySelector('moz-input-file'),
    validation: () =>
      upload().querySelector('submission-header[label="Validation"]'),
    continue: () =>
      root.querySelector<HTMLElement>(
        '.continue moz-button[variant="default"]',
      ),
    submit: () => root.querySelector<HTMLElement>('moz-page-header moz-button'),
    timeline: () =>
      root.querySelector('timeline-nav') as HTMLElement & { currStep: number },
  };
}

describe('version-submission', () => {
  describe('version upload', () => {
    it('walks through the version submission flow', async () => {
      const $ = await mountFlow('');

      // Uploading an invalid submission fails validation. Cannot continue.
      expect($.timeline().currStep).toBe(1);
      expect($.continue()?.hasAttribute('disabled')).toBe(true);
      vi.mocked(api.postUpload).mockResolvedValue(makeUpload(BAD_VALIDATION));
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() =>
          $.upload().querySelector(
            'message-bar[heading="Bad validation error"]',
          ),
        )
        .not.toBeNull();
      expect(api.postUpload).toHaveBeenLastCalledWith(
        expect.any(File),
        'listed',
      );
      expect($.timeline().currStep).toBe(2);
      expect($.continue()?.hasAttribute('disabled')).toBe(true);
      expect($.submit()?.hasAttribute('disabled')).toBe(true);

      // Changing channel resets the submission.
      $.root
        .querySelector<HTMLElement>('.continue moz-button[variant="ghost"]')
        ?.click();
      await expect.poll(() => $.step('submit-distribution')).toBeTruthy();
      pick(
        $.step('submit-distribution').querySelector('moz-visual-picker'),
        'unlisted',
      );
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
      expect($.timeline().currStep).toBe(1);
      expect($.validation()).toBeNull();
      expect(($.fileInput() as unknown as { files: File[] }).files).toEqual([]);
      expect($.continue()?.hasAttribute('disabled')).toBe(true);

      // A valid submission enables the continue button.
      const valid = makeUpload({ channel: 'unlisted' });
      vi.mocked(api.postUpload).mockResolvedValue(valid);
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      expect(api.postUpload).toHaveBeenLastCalledWith(
        expect.any(File),
        'unlisted',
      );
      expect($.submit()?.hasAttribute('disabled')).toBe(true);

      // Not making any changes to distribution doesn't reset.
      $.root
        .querySelector<HTMLElement>('.continue moz-button[variant="ghost"]')
        ?.click();
      await expect.poll(() => $.step('submit-distribution')).toBeTruthy();
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
      expect($.timeline().currStep).toBe(2);
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      expect($.validation()).not.toBeNull();

      // Removing the file resets.
      chooseFiles($.fileInput());
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(true);
      expect($.timeline().currStep).toBe(1);
      expect($.validation()).toBeNull();
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(true);

      // Pressing continue on a valid file POSTs the file.
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.source()).toBeTruthy();
      expect(api.postVersion).toHaveBeenLastCalledWith('my-addon', valid.uuid);
      expect($.submit()?.hasAttribute('disabled')).toBe(true);

      // Uploading source code patches the version.
      pick($.source().querySelector('moz-visual-picker'), 'true');
      await expect
        .poll(() => $.source().querySelector('moz-input-file'))
        .toBeTruthy();
      const archive = new File(['src'], 'src.zip');
      chooseFiles($.source().querySelector('moz-input-file'), archive);
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.step('review-submit')).toBeTruthy();
      const sourceBody = vi.mocked(api.patchVersion).mock
        .lastCall?.[2] as FormData;
      expect(sourceBody.get('source')).toBe(archive);

      // Review can submit version, PATCHing notes.
      const review = $.step('review-submit');
      await expect.poll(() => $.submit()?.hasAttribute('disabled')).toBe(false);
      Object.assign(review.querySelector('#release-notes') as Element, {
        value: 'bug fixes',
      });
      Object.assign(review.querySelector('#reviewer-notes') as Element, {
        value: 'test123',
      });
      expect($.submit()?.hasAttribute('disabled')).toBe(false);
      $.submit()?.click();
      await expect.poll(() => $.step('submit-finish')).toBeTruthy();
      expect(api.patchVersion).toHaveBeenLastCalledWith('my-addon', 20, {
        approval_notes: 'test123',
        release_notes: { 'en-US': 'bug fixes' },
      });

      // Shows finish screen.
      expect($.step('submit-finish').textContent).toContain(
        'All done! Thanks for shaping Firefox.',
      );
      expect($.continue()).toBeNull();
    });
  });

  describe('distribution', () => {
    it('reflects the selected distribution', async () => {
      const $ = await mountFlow('distribution');
      const picker = $.step('submit-distribution').querySelector(
        'moz-visual-picker',
      ) as Element & { value: string };
      expect(picker.value).toBe('listed');
      pick(picker, 'enterprise');
      await expect
        .poll(() => $.root.querySelector('submit-distribution')?.channel)
        .toBe('enterprise');
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
      expect($.root.querySelector('submit-upload')?.channel).toBe('enterprise');
    });

    it('skips the source step for enterprise', async () => {
      const $ = await mountFlow('distribution');
      pick(
        $.step('submit-distribution').querySelector('moz-visual-picker'),
        'enterprise',
      );
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
      expect($.root.querySelector('.step-count')?.textContent).toBe('Step 2/5');

      vi.mocked(api.postUpload).mockResolvedValue(
        makeUpload({ channel: 'enterprise' }),
      );
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.step('review-submit')).toBeTruthy();
      expect($.source()).toBeFalsy();
      await expect.poll(() => $.submit()?.hasAttribute('disabled')).toBe(false);
    });
  });

  describe('incomplete listing', () => {
    const INCOMPLETE = {
      ...ADDON,
      status: ADDON_STATUS.incomplete,
      summary: undefined,
      categories: [],
    };

    async function enter(path: string) {
      window.history.replaceState({}, '', `${SUBMIT}${path}`);
      const host = await mount<TestRouter>('test-router');
      await host.router.goto(`${SUBMIT}${path}`);
    }

    it.each(['', 'distribution'])(
      'redirects /submit/%s to finish an incomplete listing',
      async (path) => {
        vi.mocked(api.fetchAddons).mockResolvedValue([INCOMPLETE]);
        await enter(path);
        await expect
          .poll(() => location.pathname)
          .toMatch(/\/addon\/my-addon\/submit\/details$/);
      },
    );
  });

  describe('default channel', () => {
    const options = ($: ReturnType<typeof ui>) =>
      [
        ...$.step('submit-distribution').querySelectorAll(
          'moz-visual-picker-item',
        ),
      ].map((item) => item.getAttribute('value'));
    const picked = ($: ReturnType<typeof ui>) =>
      (
        $.step('submit-distribution').querySelector('moz-visual-picker') as
          | (Element & { value: string })
          | null
      )?.value;

    it("uploads to the last version's channel", async () => {
      vi.mocked(api.fetchVersions).mockResolvedValue([
        { ...VERSION, channel: 'unlisted' },
      ]);
      const $ = await mountFlow('');
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => vi.mocked(api.postUpload).mock.lastCall?.[1])
        .toBe('unlisted');
    });

    it('does not offer listed channel while the add-on is hidden', async () => {
      vi.mocked(api.fetchAddons).mockResolvedValue([
        { ...ADDON, visibility: 'invisible' },
      ]);
      const $ = await mountFlow('');
      await expect.poll(() => $.step('submit-distribution')).toBeTruthy();
      expect(options($)).toEqual(['unlisted', 'enterprise']);
      expect(picked($)).toBe('unlisted');
    });

    it('does not offer listed channel while the listing is rejected', async () => {
      vi.mocked(api.fetchAddons).mockResolvedValue([
        { ...ADDON, status: ADDON_STATUS.rejected },
      ]);
      const $ = await mountFlow('');
      await expect.poll(() => $.step('submit-distribution')).toBeTruthy();
      expect(options($)).toEqual(['unlisted', 'enterprise']);
    });
  });

  describe('first listed version', () => {
    const UNLISTED_ONLY: Addon = {
      ...ADDON,
      status: ADDON_STATUS.incomplete,
      channels: ['unlisted'],
      summary: undefined,
      categories: [],
    };

    beforeEach(() => {
      vi.mocked(api.fetchAddons).mockResolvedValue([UNLISTED_ONLY]);
      vi.mocked(api.fetchVersions).mockResolvedValue([
        { ...VERSION, channel: 'unlisted' },
      ]);
    });

    it('collects the listing before creating the version', async () => {
      const $ = await mountFlow('distribution');
      pick(
        $.step('submit-distribution').querySelector('moz-visual-picker'),
        'listed',
      );
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
      const labels = () =>
        [...$.root.querySelectorAll('moz-breadcrumb')].map(
          (b) => b.textContent,
        );
      const timeline = $.timeline() as unknown as {
        sections: { title: string }[];
      };
      expect(timeline.sections.map((section) => section.title)).toEqual([
        'Upload version',
        'Create your listing',
        'Review',
      ]);

      // The upload doesn't create the version...
      const valid = makeUpload();
      vi.mocked(api.postUpload).mockResolvedValue(valid);
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.source()).toBeTruthy();
      expect(location.pathname).toBe(`${SUBMIT}source`);
      expect(api.postVersion).not.toHaveBeenCalled();

      // ...the listing step does.
      pick($.source().querySelectorAll('moz-visual-picker')[1], 'false');
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect
        .poll(() => $.root.querySelector('.outlet submit-listing'))
        .toBeTruthy();
      expect(location.pathname).toBe(`${SUBMIT}listing`);
      expect(labels().at(-1)).toBe('Listing details');
      const listing = $.root.querySelector<SubmitListing>(
        '.outlet submit-listing',
      );
      expect(listing?.upload).toBe(valid.uuid);
      await expect
        .poll(() => listing?.shadowRoot?.querySelector('listing-details-card'))
        .toBeTruthy();
      expect(
        listing?.shadowRoot?.querySelector('listing-details-card')?.showListing,
      ).toBe(true);
      expect(api.postVersion).not.toHaveBeenCalled();
    });
  });

  describe('upload', () => {
    let $: ReturnType<typeof ui>;

    beforeEach(async () => {
      $ = await mountFlow('');
    });

    it('shows no validation errors if there are none', async () => {
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.upload().textContent)
        .toContain('No errors found.');
      expect($.validation()).not.toBeNull();
      expect($.upload().querySelector('message-bar')).toBeNull();
      expect($.continue()?.hasAttribute('disabled')).toBe(false);
    });

    it('hides validation until a package is uploaded', async () => {
      expect($.validation()).toBeNull();
    });

    it('shows validation messages once processed', async () => {
      vi.mocked(api.postUpload).mockResolvedValue(makeUpload(BAD_VALIDATION));
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() =>
          $.upload().querySelector(
            'message-bar[heading="Bad validation error"]',
          ),
        )
        .not.toBeNull();
    });

    it('errors when the upload fails', async () => {
      vi.mocked(api.postUpload).mockRejectedValue(
        new Error('Everything exploded'),
      );
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.upload().querySelector('message-bar[type="error"]'))
        .not.toBeNull();
      const bar = $.upload().querySelector('message-bar');
      expect(bar?.getAttribute('heading')).toBe('Upload failed');
      expect($.validation()).toBeNull();
    });
  });

  describe('source code', () => {
    let $: ReturnType<typeof ui>;
    let yesPicker: Element;
    let noPicker: Element;
    const fileInput = () => $.source().querySelector('moz-input-file');

    beforeEach(async () => {
      $ = await mountFlow('20/source');
      [yesPicker, noPicker] = $.source().querySelectorAll('moz-visual-picker');
    });

    it('disables Continue until a choice is made', async () => {
      expect($.continue()?.hasAttribute('disabled')).toBe(true);
      expect(fileInput()).toBeNull();
    });

    it('requires a source archive when tools are used', async () => {
      pick(yesPicker, 'true');
      await expect.poll(() => fileInput()).toBeTruthy();
      expect($.continue()?.hasAttribute('disabled')).toBe(true);

      chooseFiles(fileInput(), new File(['s'], 'src.zip'));
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
    });

    it('enables Continue when no tools are used', async () => {
      pick(noPicker, 'false');
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      expect(fileInput()).toBeNull();
    });
  });

  describe('site status submit notice', () => {
    it('surfaces the submission notice from the site status', async () => {
      vi.mocked(api.fetchProfile).mockResolvedValue({
        id: '1',
        name: 'Kate',
        siteStatus: {
          readOnly: false,
          siteNotice: null,
          submissionNotice: 'Submissions are temporarily paused.',
        },
      });
      const $ = await mountFlow('');
      await expect
        .poll(() => $.root.querySelector('#submit-status-banner')?.textContent)
        .toContain('Submissions are temporarily paused.');
    });

    it('renders no notice when the site status has none', async () => {
      const $ = await mountFlow('');
      // Let the profile query settle; the default status has no submit notice.
      await expect
        .poll(() => vi.mocked(api.fetchProfile).mock.calls.length)
        .toBeGreaterThan(0);
      expect($.root.querySelector('#submit-status-banner')).toBeNull();
    });

    it("falls back to the add-on's per-channel notice when the site has none", async () => {
      vi.mocked(api.fetchAddons).mockResolvedValue([
        makeAddon({ listed: 'Listed submissions are paused.' }),
      ]);
      // Defaults to the 'listed' channel.
      const $ = await mountFlow('');
      await expect
        .poll(() => $.root.querySelector('#submit-status-banner')?.textContent)
        .toContain('Listed submissions are paused.');
    });

    it('shows no notice when the current channel has a null warning', async () => {
      // The API returns every channel, with null where there's no warning.
      vi.mocked(api.fetchAddons).mockResolvedValue([
        makeAddon({ listed: null, unlisted: null, enterprise: null }),
      ]);
      const $ = await mountFlow('');
      await expect
        .poll(() => vi.mocked(api.fetchAddons).mock.calls.length)
        .toBeGreaterThan(0);
      expect($.root.querySelector('#submit-status-banner')).toBeNull();
    });

    it('follows the selected channel', async () => {
      vi.mocked(api.fetchAddons).mockResolvedValue([
        makeAddon({
          listed: 'Listed submissions are paused.',
          unlisted: 'Unlisted submissions are paused.',
        }),
      ]);
      const $ = await mountFlow('distribution');

      // Starts on the default 'listed' channel.
      await expect
        .poll(() => $.root.querySelector('#submit-status-banner')?.textContent)
        .toContain('Listed submissions are paused.');

      // Choosing another channel swaps the notice.
      pick(
        $.step('submit-distribution').querySelector('moz-visual-picker'),
        'unlisted',
      );
      await expect
        .poll(() => $.root.querySelector('#submit-status-banner')?.textContent)
        .toContain('Unlisted submissions are paused.');
    });

    it('prefers the site-status notice over the add-on notice', async () => {
      vi.mocked(api.fetchProfile).mockResolvedValue({
        id: '1',
        name: 'Kate',
        siteStatus: {
          readOnly: false,
          siteNotice: null,
          submissionNotice: 'Site-wide pause.',
        },
      });
      vi.mocked(api.fetchAddons).mockResolvedValue([
        makeAddon({ listed: 'Listed submissions are paused.' }),
      ]);
      const $ = await mountFlow('');
      await expect
        .poll(() => $.root.querySelector('#submit-status-banner')?.textContent)
        .toContain('Site-wide pause.');
      expect(
        $.root.querySelector('#submit-status-banner')?.textContent,
      ).not.toContain('Listed submissions are paused.');
    });
  });

  describe('review step', () => {
    it('shows the correct fields', async () => {
      queryClient.setQueryData(queryKeys.version('my-addon', 20), VERSION);
      const $ = await mountFlow('20/details');
      const review = $.step('review-submit');
      const fields = Object.fromEntries(
        [...review.querySelectorAll('dl > div')].map((d) => [
          d.querySelector('dt')?.textContent?.trim(),
          d.querySelector('dd')?.textContent?.trim(),
        ]),
      );
      expect(fields).toEqual({
        Package: 'addon.xpi',
        'Version number': '1.0.0',
        Distribution: 'AMO',
      });
      expect(review.querySelector('#release-notes')).not.toBeNull();
      expect(review.querySelector('#reviewer-notes')).not.toBeNull();
    });
  });
});
