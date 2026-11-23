import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { Addon } from '../data';

@customElement('theme-preview')
export class ThemePreview extends LitElement {
  @property({ attribute: false }) addon!: Addon;

  static styles = css`
    :host {
      display: block;
    }
    .bar {
      height: 10px;
      border-radius: 999px;
    }
    .preview {
      display: block;
      width: 100%;
      height: 96px;
      object-fit: cover;
      border-radius: var(--border-radius-medium, 8px);
    }
  `;

  render() {
    const { previewUrl, gradient } = this.addon;
    return previewUrl
      ? html`<img class="preview" src=${previewUrl} alt="" />`
      : html`<div class="bar" style="background: ${gradient};"></div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'theme-preview': ThemePreview;
  }
}
