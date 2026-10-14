import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../../src/data/http';
import { FormController, routeApiError } from '../../../src/foundations/form';

// Minimal ReactiveControllerHost stand-in that records requestUpdate calls.
function host() {
  return {
    addController: vi.fn(),
    removeController: vi.fn(),
    requestUpdate: vi.fn(),
    updateComplete: Promise.resolve(true),
  };
}

type Draft = { name?: string; listed?: boolean };

describe('FormController', () => {
  it('start seeds the draft and enters edit mode', () => {
    const form = new FormController<Draft>(host());
    form.start({ name: 'Kate', listed: true });
    expect(form.editing).toBe(true);
    expect(form.value('name')).toBe('Kate');
  });

  it('set updates a field immutably and cancel clears state', () => {
    const h = host();
    const form = new FormController<Draft>(h);
    form.start({ name: 'Kate' });
    form.set('name', 'Lee');
    expect(form.value('name')).toBe('Lee');
    form.cancel();
    expect(form.editing).toBe(false);
    expect(h.requestUpdate).toHaveBeenCalled();
  });

  it('submit runs the callback and leaves edit mode on success', async () => {
    const form = new FormController<Draft>(host());
    form.start({ name: 'Kate' });
    const run = vi.fn(async () => {});
    await form.submit(run);
    expect(run).toHaveBeenCalledWith({ name: 'Kate' });
    expect(form.editing).toBe(false);
    expect(form.saving).toBe(false);
  });

  it('submit routes an ApiError onto field + general errors', async () => {
    const form = new FormController<Draft>(host());
    form.start({ name: 'Kate' });
    await form.submit(async () => {
      throw new ApiError(400, 'bad', { name: 'Too long.' }, 'General problem.');
    });
    expect(form.editing).toBe(true); // stays open so the user can fix it
    expect(form.fieldError('name')).toBe('Too long.');
    expect(form.error).toBe('General problem.');
  });
});

describe('routeApiError', () => {
  it('falls back to the summary when an ApiError has no detail or fields', () => {
    expect(routeApiError(new ApiError(500, 'AMO API responded 500'))).toEqual({
      error: 'AMO API responded 500',
      fieldErrors: {},
    });
  });

  it('handles non-ApiError throwables', () => {
    expect(routeApiError(new Error('boom'))).toEqual({
      error: 'boom',
      fieldErrors: {},
    });
  });
});
