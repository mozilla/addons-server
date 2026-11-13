import {
  type CSSResultGroup,
  css,
  html,
  LitElement,
  nothing,
  type PropertyValues,
} from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { emit } from '../../../utils/helper';
import '../../../foundations/components/message-bar';

export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export function errorBar(heading: string, message?: string) {
  return message
    ? html`<message-bar
        type="error"
        heading=${heading}
        description=${message}
      ></message-bar>`
    : nothing;
}

export abstract class SubmissionStep extends LitElement {
  static styles: CSSResultGroup = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--space-large);
    }
  `;

  protected abstract get ready(): boolean;

  connectedCallback() {
    super.connectedCallback();
    if (this.hasUpdated) this.requestUpdate();
  }

  updated(changed: PropertyValues) {
    super.updated(changed);
    emit(this, 'step-ready', { ready: this.ready });
  }

  async submit(): Promise<boolean> {
    return true;
  }
}

@customElement('submission-header')
export class SubmissionHeader extends LitElement {
  static styles = css`
    :host {
      display: flex;
      flex-direction: column;
      gap: 0.25em;
    }
    legend {
      padding: 0;
      font-weight: var(--font-weight-heading);
    }
    .description {
      margin: 0;
      color: var(--text-color-deemphasized);
      font-size: var(--font-size-small);
    }
  `;

  @property() label?: string;
  @property() description?: string;

  render() {
    return html`
      ${this.label && html`<legend>${this.label}</legend>`}
      ${this.description && html`<p class="description">${this.description}</p>`}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submission-header': SubmissionHeader;
  }
}
