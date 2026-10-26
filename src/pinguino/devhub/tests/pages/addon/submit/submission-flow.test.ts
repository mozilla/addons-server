import 'urlpattern-polyfill';

import { Router } from '@lit-labs/router';
import { html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { queryClient, queryKeys } from '../../../../src/data';
import * as api from '../../../../src/data/api';
import type { FileUpload, Version } from '../../../../src/data/types';
import '../../../../src/pages/addon/versions/submit/main';
import { mount, settle } from '../../../helpers/fixture';

vi.mock('../../../../src/data/api');

@customElement('test-router')
class TestRouter extends LitElement {
  router = new Router(this, [
    {
      path: '/submit/*',
      render: () => html`<addon-submission slug="my-addon"></addon-submission>`,
    },
  ]);

  render() {
    return this.router.outlet();
  }
}

const VERSION: Version = {
  id: 20,
  version: '1.0.0',
  channel: 'listed',
  file: {
    id: 1,
    url: 'https://example.com/files/addon.xpi',
    size: 1,
    status: 'public',
  },
  release_notes: null,
  approval_notes: '',
  source: null,
};

const makeUpload = (args: Partial<FileUpload> = {}): FileUpload => ({
  uuid: crypto.randomUUID(),
  channel: 'listed',
  processed: true,
  submitted: false,
  url: '',
  valid: true,
  validation: null,
  version: '1.0.0',
  ...args,
});

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
  vi.mocked(api.postUpload).mockResolvedValue(makeUpload());
  vi.mocked(api.fetchUpload).mockImplementation(
    () => vi.mocked(api.postUpload).mock.results.at(-1)?.value,
  );
  vi.mocked(api.fetchVersion).mockResolvedValue(VERSION);
  vi.mocked(api.postVersion).mockResolvedValue(VERSION);
  vi.mocked(api.patchVersion).mockResolvedValue(VERSION);
});

async function mountFlow(path: string) {
  window.history.replaceState({}, '', `/submit/${path}`);
  const host = await mount<TestRouter>('test-router');
  await host.router.goto(`/submit/${path}`);
  await settle(host);
  const el = host.shadowRoot?.querySelector('addon-submission');
  if (!el) throw new Error('expected addon-submission in the DOM');
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

describe('addon-submission', () => {
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
        'Congrats, your version is submitted',
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
