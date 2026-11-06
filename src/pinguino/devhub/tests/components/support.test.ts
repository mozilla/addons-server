import { describe, expect, it, vi } from 'vitest';

const { postSupport } = vi.hoisted(() => ({
  postSupport: vi.fn(async (payload: unknown) => payload),
}));
vi.mock('../../src/data/api', () => ({ postSupport }));

import type { Support } from '../../src/components/support';
import '../../src/components/support';
import { ApiError } from '../../src/data/http';
import { mount } from '../helpers/fixture';

type Field = HTMLElement & { value: string };

async function form() {
  const el = await mount<Support>('support-form');
  return { el, root: el.shadowRoot as ShadowRoot };
}

// Drives the three inputs the way a user would: set the value and fire the
// event each field's handler listens for (input for text, change for select).
async function fill(
  el: Support,
  root: ShadowRoot,
  values: { summary: string; category: string; body: string },
) {
  const summary = root.querySelector('moz-input-text') as Field;
  const category = root.querySelector('moz-select') as Field;
  const body = root.querySelector('moz-textarea') as Field;

  summary.value = values.summary;
  summary.dispatchEvent(new Event('input'));
  category.value = values.category;
  category.dispatchEvent(new Event('change'));
  body.value = values.body;
  body.dispatchEvent(new Event('input'));
  await el.updateComplete;
}

function submit(root: ShadowRoot) {
  const el = root.querySelector('form') as HTMLFormElement;
  el.dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('support-form', () => {
  it('renders the fieldset heading and all three inputs', async () => {
    const { root } = await form();
    expect(root.querySelector('moz-fieldset')?.getAttribute('label')).toBe(
      'Get support for extensions and themes',
    );
    expect(root.querySelector('moz-input-text')).not.toBeNull();
    expect(root.querySelector('moz-select')).not.toBeNull();
    expect(root.querySelector('moz-textarea')).not.toBeNull();
  });

  it('passes the field helper options through to the inputs', async () => {
    const { root } = await form();
    const summary = root.querySelector('moz-input-text');
    const body = root.querySelector('moz-textarea');
    expect(summary?.getAttribute('placeholder')).toBe(
      'Summarise the issue in a few words',
    );
    expect(body?.getAttribute('maxlength')).toBe('10000');
    expect(body?.getAttribute('rows')).toBe('8');
  });

  it('submits the entered values to postSupport', async () => {
    const { el, root } = await form();
    await fill(el, root, {
      summary: 'Login broken',
      category: 'policy',
      body: 'I cannot sign in.',
    });

    submit(root);

    await vi.waitFor(() =>
      expect(postSupport).toHaveBeenCalledWith({
        category: 'policy',
        summary: 'Login broken',
        body: 'I cannot sign in.',
      }),
    );
  });

  it('shows a success message and clears the inputs after submitting', async () => {
    const { el, root } = await form();
    await fill(el, root, {
      summary: 'Login broken',
      category: 'other',
      body: 'Details.',
    });

    submit(root);

    await vi.waitFor(() =>
      expect(
        root.querySelector('moz-message-bar[type="success"]')?.textContent,
      ).toContain('Your support request has been submitted'),
    );
    // The draft is reset so the form is ready for another request.
    expect((root.querySelector('moz-input-text') as Field).value).toBe('');
    expect((root.querySelector('moz-textarea') as Field).value).toBe('');
  });

  it('surfaces a general error and field errors when the request fails', async () => {
    postSupport.mockRejectedValueOnce(
      new ApiError(
        400,
        'Bad Request',
        { category: 'This field is required.' },
        'Please fix the errors below.',
      ),
    );
    const { el, root } = await form();
    await fill(el, root, { summary: 's', category: 'policy', body: 'b' });

    submit(root);

    await vi.waitFor(() =>
      expect(
        root.querySelector('moz-message-bar[type="error"]')?.textContent,
      ).toContain('Please fix the errors below.'),
    );
    expect(root.querySelector('moz-select')?.getAttribute('error')).toBe(
      'This field is required.',
    );
    // No success message on failure.
    expect(root.querySelector('moz-message-bar[type="success"]')).toBeNull();
  });

  it('disables the submit button while the request is in flight', async () => {
    let resolve: (value: unknown) => void = () => {};
    postSupport.mockReturnValueOnce(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const { el, root } = await form();
    await fill(el, root, { summary: 's', category: 'policy', body: 'b' });

    submit(root);
    await el.updateComplete;

    const button = root.querySelector('moz-button') as HTMLElement;
    expect(button.hasAttribute('disabled')).toBe(true);
    expect(button.textContent).toContain('Sending…');

    resolve(undefined);
    await vi.waitFor(() =>
      expect(root.querySelector('moz-button')?.hasAttribute('disabled')).toBe(
        false,
      ),
    );
  });
});
