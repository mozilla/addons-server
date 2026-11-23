import { describe, expect, it } from 'vitest';
import type { SubmitSource } from '../../../../src/pages/addon/submit/templates/source';
import '../../../../src/pages/addon/submit/templates/source';
import { mount, settle } from '../../../helpers/fixture';

// The step only offers the picker once the developer says they use build tools.
async function sourceStep() {
  const el = await mount<SubmitSource>('submit-source', { slug: 'ad-blocker' });
  const root = el.shadowRoot as ShadowRoot;
  root.querySelector('moz-visual-picker')?.dispatchEvent(new Event('change'));
  await settle(el);
  return {
    el,
    root,
    input: () => root.querySelector('moz-input-file'),
    error: () =>
      root
        .querySelector('message-bar[type="error"]')
        ?.getAttribute('description') ?? undefined,
  };
}

async function choose($: Awaited<ReturnType<typeof sourceStep>>, name: string) {
  const input = $.input();
  if (!input) throw new Error('expected moz-input-file in the DOM');
  Object.assign(input, { files: [new File(['x'], name)] });
  input.dispatchEvent(new Event('change'));
  await settle($.el);
}

// The control reports rejections rather than rendering them, so without
// handling this the file fails silently.
async function reject(
  $: Awaited<ReturnType<typeof sourceStep>>,
  reason: 'type' | 'size',
) {
  $.input()?.dispatchEvent(
    new CustomEvent('moz-input-file:rejected', {
      bubbles: true,
      composed: true,
      detail: { reason },
    }),
  );
  await settle($.el);
}

describe('submit-source archive formats', () => {
  it('names the supported formats when the control turns a file away', async () => {
    const $ = await sourceStep();
    await reject($, 'type');
    expect($.error()).toContain('.zip, .tar.gz, .tgz, .tar.bz2');
  });

  // Both the control and the file dialog filter on this, so a format missing
  // here can't be picked at all. .tar.gz and .tar.bz2 were the reported bug.
  it('offers every supported format to the file picker', async () => {
    const $ = await sourceStep();
    const accept = ($.input()?.getAttribute('accept') ?? '').split(',');
    expect(accept).toEqual(['.zip', '.tar.gz', '.tgz', '.tar.bz2']);
  });

  it('reports a file the control turned away for size', async () => {
    const $ = await sourceStep();
    await reject($, 'size');
    expect($.error()).toContain('200 MB');
  });

  it('clears the rejection once an accepted file is picked', async () => {
    const $ = await sourceStep();
    await reject($, 'type');
    await choose($, 'source.tar.gz');
    expect($.error()).toBeUndefined();
  });
});
