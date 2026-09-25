import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';

const NAV = [
  'My Add-ons',
  'Documentation',
  'Tools',
  'Community & Support',
  'Extension Workshop',
];

@customElement('devhub-header')
export class DevhubHeader extends LitElement {
  static styles = css`
    :host {
      display: block;
      border-bottom: 1px solid
        light-dark(rgba(21, 20, 26, 0.12), rgba(251, 251, 254, 0.16));
    }
    .bar {
      display: flex;
      align-items: center;
      gap: var(--space-large);
      padding-block: var(--space-medium);
    }
    .brand {
      font-weight: 700;
    }
    nav {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-large);
    }
    a {
      color: var(--text-color, CanvasText);
      text-decoration: none;
      font-size: 0.9rem;
    }
    a:hover {
      text-decoration: underline;
    }
    .spacer {
      margin-inline-start: auto;
    }
  `;

  render() {
    return html`
      <div class="bar">
        <a class="brand" href="/pinguino/">Add-ons</a>
        <nav>
          ${NAV.map((label) => html`<a href="/pinguino/">${label}</a>`)}
        </nav>
        <span class="spacer"></span>
        <moz-icon name="settings"></moz-icon>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-header': DevhubHeader;
  }
}
