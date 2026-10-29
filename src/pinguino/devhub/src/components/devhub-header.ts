import { css, html, LitElement } from 'lit';
import { customElement } from 'lit/decorators.js';
import { BASE } from '../base';
import { classicPath } from '../navigation';

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

  // Switch to the classic devhub via the Django endpoint that flips the PINGUINO
  // cookie; the bare href is a no-JS fallback (view defaults to the index).
  #switchToClassic = (event: Event) => {
    event.preventDefault();
    const path = classicPath(location.pathname, BASE) + location.search;
    location.href = `${BASE}/switch-pinguino?path=${encodeURIComponent(path)}`;
  };

  render() {
    return html`
      <div class="bar">
        <a class="brand" href="${BASE}/">Add-ons</a>
        <nav>
          ${NAV.map((label) => html`<a href="${BASE}/">${label}</a>`)}
          <a
            rel="external"
            href="${BASE}/switch-pinguino"
            @click=${this.#switchToClassic}
            >Switch back to the old Developer Hub</a
          >
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
