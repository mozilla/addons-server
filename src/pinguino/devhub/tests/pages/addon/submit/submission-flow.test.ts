import 'urlpattern-polyfill';

import { Router } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BASE, MAX_UPLOAD_SIZE } from '../../../../src/base';
import { queryClient, queryKeys } from '../../../../src/data';
import * as api from '../../../../src/data/api';
import { ADDON_STATUS } from '../../../../src/data/statuses';
import type {
  Addon,
  AddonDistribution,
  FileUpload,
  ValidationMessage,
  Version,
} from '../../../../src/data/types';
import type { SubmitListing } from '../../../../src/pages/addon/submit/templates/listing';
import '../../../../src/pages/addon/versions/submit/main';
import { DEFAULT_VERSION, mount, settle } from '../../../helpers/fixture';

vi.mock('../../../../src/data/api');

const SUBMIT = `${BASE}/addon/my-addon/versions/submit/`;

// fetchAddons resolves one page per kind; the flow only reads the add-on, so
// the same page answers both calls.
function mockAddons(...addons: Addon[]) {
  vi.mocked(api.fetchAddons).mockResolvedValue({
    results: addons,
    count: addons.length,
  });
}

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
  mockAddons();
  vi.mocked(api.postUpload).mockResolvedValue(makeUpload());
  vi.mocked(api.fetchUpload).mockImplementation(
    () => vi.mocked(api.postUpload).mock.results.at(-1)?.value,
  );
  vi.mocked(api.fetchVersion).mockResolvedValue(VERSION);
  vi.mocked(api.postVersion).mockResolvedValue(VERSION);
  vi.mocked(api.patchVersion).mockResolvedValue(VERSION);
  mockAddons(ADDON);
  vi.mocked(api.fetchVersions).mockResolvedValue({
    items: [VERSION],
    total: 1,
  });
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

// moz-input-file isn't registered here. clear() has to report a change like
// the real control's does, or the steps never see the selection drop.
type StubInput = Element & { files: File[]; clear(): void };

function stubInput(input: Element | null): StubInput {
  if (!input) throw new Error('expected moz-input-file in the DOM');
  const stub = input as StubInput;
  if (typeof stub.clear !== 'function') {
    stub.files = [];
    stub.clear = () => {
      if (!stub.files.length) return;
      stub.files = [];
      stub.dispatchEvent(new Event('change'));
    };
  }
  return stub;
}

function chooseFiles(input: Element | null, ...files: File[]) {
  const stub = stubInput(input);
  stub.files = files;
  stub.dispatchEvent(new Event('change'));
}

function rejectFile(input: Element | null, reason: 'type' | 'size') {
  stubInput(input).dispatchEvent(
    new CustomEvent('moz-input-file:rejected', {
      bubbles: true,
      composed: true,
      detail: {
        file: new File(['x'], 'notes.txt'),
        reason,
        maxSize: reason === 'size' ? MAX_UPLOAD_SIZE : undefined,
      },
    }),
  );
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

      // The flow opens on the distribution step; accept the default and continue.
      expect($.timeline().currStep).toBe(0);
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();

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
      const $ = await mountFlow('');
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
      const $ = await mountFlow('');
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
        mockAddons(INCOMPLETE);
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
      vi.mocked(api.fetchVersions).mockResolvedValue({
        items: [{ ...VERSION, channel: 'unlisted' }],
        total: 1,
      });
      const $ = await mountFlow('');
      // The distribution step opens pre-selected to the last version's channel.
      expect(picked($)).toBe('unlisted');
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => vi.mocked(api.postUpload).mock.lastCall?.[1])
        .toBe('unlisted');
    });

    it('does not offer listed channel while the add-on is hidden', async () => {
      mockAddons({ ...ADDON, visibility: 'invisible' });
      const $ = await mountFlow('');
      await expect.poll(() => $.step('submit-distribution')).toBeTruthy();
      expect(options($)).toEqual(['unlisted', 'enterprise']);
      expect(picked($)).toBe('unlisted');
    });

    it('does not offer listed channel while the listing is rejected', async () => {
      mockAddons({ ...ADDON, status: ADDON_STATUS.rejected });
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
      mockAddons(UNLISTED_ONLY);
      vi.mocked(api.fetchVersions).mockResolvedValue({
        items: [{ ...VERSION, channel: 'unlisted' }],
        total: 1,
      });
    });

    it('collects the listing before creating the version', async () => {
      const $ = await mountFlow('');
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

    // The upload step follows the distribution step; accept the default to reach it.
    beforeEach(async () => {
      $ = await mountFlow('');
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);
      $.continue()?.click();
      await expect.poll(() => $.upload()).toBeTruthy();
    });

    it('shows no validation errors if there are none', async () => {
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() =>
          $.upload()
            .querySelector('message-bar[type="info"]')
            ?.getAttribute('heading'),
        )
        .toBe('Your add-on was validated with no errors or warnings.');
      expect($.validation()).not.toBeNull();
      expect($.upload().querySelectorAll('message-bar')).toHaveLength(1);
      expect($.continue()?.hasAttribute('disabled')).toBe(false);
    });

    describe('validation message grouping', () => {
      const headings = (selector: string) =>
        [...$.upload().querySelectorAll(selector)].map((m) =>
          m.getAttribute('heading'),
        );
      const primary = () =>
        headings('submission-header + .messages > message-bar');
      const secondary = () => headings('moz-details message-bar');

      async function uploadWith(...messages: ValidationMessage[]) {
        const count = (type: string) =>
          messages.filter((m) => m.type === type).length;
        vi.mocked(api.postUpload).mockResolvedValue(
          makeUpload({
            validation: {
              errors: count('error'),
              warnings: count('warning'),
              notices: 0,
              messages,
            },
          }),
        );
        chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
        await expect.poll(() => $.validation()).not.toBeNull();
      }

      it('shows all errors', async () => {
        await uploadWith(
          { type: 'error', message: 'error 1' },
          { type: 'error', message: 'error 2' },
          { type: 'error', message: 'error 3' },
          { type: 'error', message: 'error 4' },
        );
        expect(primary()).toEqual(['error 1', 'error 2', 'error 3', 'error 4']);
        expect($.upload().querySelector('moz-details')).toBeNull();
      });

      it('shows errors and hides warnings', async () => {
        await uploadWith(
          { type: 'warning', message: 'warning 1' },
          { type: 'warning', message: 'warning 2' },
          { type: 'warning', message: 'warning 3' },
          { type: 'error', message: 'error 1' },
          { type: 'error', message: 'error 2' },
        );
        expect(primary()).toEqual(['error 1', 'error 2']);
        expect(secondary()).toEqual(['warning 1', 'warning 2', 'warning 3']);
      });

      it('no errors shows the first 3 warnings and hides the rest', async () => {
        await uploadWith(
          { type: 'warning', message: 'warning 1' },
          { type: 'warning', message: 'warning 2' },
          { type: 'warning', message: 'warning 3' },
          { type: 'warning', message: 'warning 4' },
          { type: 'warning', message: 'warning 5' },
        );
        expect(primary()).toEqual(['warning 1', 'warning 2', 'warning 3']);
        expect(secondary()).toEqual(['warning 4', 'warning 5']);
      });
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

    it('offers only package formats to the file picker', () => {
      expect($.fileInput()?.getAttribute('accept')).toBe('.zip,.xpi,.crx');
    });

    it.each([
      ['type', "The filetype you uploaded isn't recognized."],
      ['size', 'Your file exceeds the maximum size of 200MB.'],
    ] as const)(
      'reports a package turned away for %s',
      async (reason, text) => {
        rejectFile($.fileInput(), reason);
        await expect
          .poll(() => $.upload().querySelector('message-bar[type="error"]'))
          .not.toBeNull();
        expect(
          $.upload()
            .querySelector('message-bar[type="error"]')
            ?.getAttribute('description'),
        ).toBe(text);
        expect(api.postUpload).not.toHaveBeenCalled();
      },
    );

    it('drops an already-valid upload when a later file is turned away', async () => {
      chooseFiles($.fileInput(), new File(['xpi'], 'my-addon.xpi'));
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(false);

      rejectFile($.fileInput(), 'size');
      await expect
        .poll(() => $.continue()?.hasAttribute('disabled'))
        .toBe(true);
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

    // Both the control and the file dialog filter on this, so a format missing
    // here can't be picked at all. .tar.gz and .tar.bz2 were the reported bug.
    it('offers every supported archive format to the file picker', async () => {
      pick(yesPicker, 'true');
      await expect.poll(() => fileInput()).toBeTruthy();
      expect(fileInput()?.getAttribute('accept')).toBe(
        '.zip,.tar.gz,.tgz,.tar.bz2',
      );
    });

    it.each([
      ['type', "The filetype you uploaded isn't recognized."],
      ['size', 'Your file exceeds the maximum size of 200MB.'],
    ] as const)(
      'reports an archive turned away for %s',
      async (reason, text) => {
        pick(yesPicker, 'true');
        await expect.poll(() => fileInput()).toBeTruthy();

        rejectFile(fileInput(), reason);
        await expect
          .poll(() => $.source().querySelector('message-bar[type="error"]'))
          .not.toBeNull();
        const bar = $.source().querySelector('message-bar[type="error"]');
        expect(bar?.getAttribute('description')).toBe(text);
        // It belongs beside the picker it's about, not under the "No" branch.
        expect(bar?.parentElement?.contains(fileInput() as Node)).toBe(true);
        expect($.continue()?.hasAttribute('disabled')).toBe(true);
      },
    );

    it('clears the rejection once an accepted archive is picked', async () => {
      pick(yesPicker, 'true');
      await expect.poll(() => fileInput()).toBeTruthy();
      rejectFile(fileInput(), 'type');
      await expect
        .poll(() => $.source().querySelector('message-bar[type="error"]'))
        .not.toBeNull();

      chooseFiles(fileInput(), new File(['s'], 'src.tar.gz'));
      await expect
        .poll(() => $.source().querySelector('message-bar[type="error"]'))
        .toBeNull();
      expect($.continue()?.hasAttribute('disabled')).toBe(false);
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
      mockAddons(makeAddon({ listed: 'Listed submissions are paused.' }));
      // Defaults to the 'listed' channel.
      const $ = await mountFlow('');
      await expect
        .poll(() => $.root.querySelector('#submit-status-banner')?.textContent)
        .toContain('Listed submissions are paused.');
    });

    it('shows no notice when the current channel has a null warning', async () => {
      // The API returns every channel, with null where there's no warning.
      mockAddons(makeAddon({ listed: null, unlisted: null, enterprise: null }));
      const $ = await mountFlow('');
      await expect
        .poll(() => vi.mocked(api.fetchAddons).mock.calls.length)
        .toBeGreaterThan(0);
      expect($.root.querySelector('#submit-status-banner')).toBeNull();
    });

    it('follows the selected channel', async () => {
      mockAddons(
        makeAddon({
          listed: 'Listed submissions are paused.',
          unlisted: 'Unlisted submissions are paused.',
        }),
      );
      const $ = await mountFlow('');

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
      mockAddons(makeAddon({ listed: 'Listed submissions are paused.' }));
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
