import type { InputType } from '@mozilla/acorn-web-components';
import { html } from 'lit';
import type { FormController } from './form-controller';

// Text input bound to a FormController field: value, inline error, and input
// wiring. `name` is the draft/API field key.
export function textField<D extends object>(
  form: FormController<D>,
  name: keyof D & string,
  label: string,
  type: InputType = 'text',
) {
  return html`<moz-input-text
    label=${label}
    type=${type}
    full-width
    error=${form.fieldError(name)}
    .value=${(form.value(name) as string) ?? ''}
    @input=${(e: Event) =>
      form.set(name, (e.target as HTMLInputElement).value as D[typeof name])}
  ></moz-input-text>`;
}

export function textArea<D extends object>(
  form: FormController<D>,
  name: keyof D & string,
  label: string,
) {
  return html`<moz-textarea
    label=${label}
    full-width
    error=${form.fieldError(name)}
    .value=${(form.value(name) as string) ?? ''}
    @input=${(e: Event) =>
      form.set(name, (e.target as HTMLTextAreaElement).value as D[typeof name])}
  ></moz-textarea>`;
}
