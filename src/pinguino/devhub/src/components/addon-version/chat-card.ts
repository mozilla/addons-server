import { css, html, LitElement, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import type { Update } from '../../data';
import { ACTIVITY_TAGS, sanitizeHTML } from '../../utils/sanitizeHTML';

@customElement('chat-card')
export class ChatCard extends LitElement {
  @property({ attribute: false }) item!: Update;

  static styles = css`
    :host {
      display: block;
    }
    .card {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--space-medium);
      padding: var(--space-large);
      border-radius: var(--border-radius-medium, 8px);
      background: var(--background-color-canvas);
    }
    .head {
      display: flex;
      align-items: center;
      gap: var(--space-medium);
      min-width: 0;
    }
    .head p {
      margin: 0;
    }
    .headline {
      font-weight: 600;
    }
    .date {
      color: var(--text-color-deemphasized, GrayText);
    }
    .message {
      overflow-wrap: anywhere;
    }
    .message p,
    .message ul {
      margin: 0;
    }
    .message ul {
      padding-inline-start: var(--space-xlarge, 1.5rem);
    }
    .foot {
      display: flex;
    }
  `;

  async #copy() {
    const text = this.item?.message;
    if (text && window.isSecureContext) {
      await navigator.clipboard?.writeText(text);
    }
  }

  render() {
    const u = this.item;
    return html`
      <div class="card">
        <div class="head">
          <!-- TODO: The activity API does not expose the type of the activity. -->
          <moz-status-dot icon type="information"></moz-status-dot>
          <div>
            <p class="headline">
              ${unsafeHTML(sanitizeHTML(u.title, ACTIVITY_TAGS))}
            </p>
            ${u.date ? html`<p class="date">${u.date}</p>` : nothing}
          </div>
        </div>
        ${
          u.message
            ? html`
              <div class="message">
                ${unsafeHTML(sanitizeHTML(u.message, ACTIVITY_TAGS))}
              </div>
              <div class="foot">
                <moz-button
                  variant="ghost"
                  icon-start="copy"
                  icon-only="Copy message"
                  @click=${this.#copy}
                  size="small"
                ></moz-button>
              </div>
            `
            : nothing
        }
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'chat-card': ChatCard;
  }
}
