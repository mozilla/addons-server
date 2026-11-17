import { css, html, LitElement } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { PREVIEW_BLOG_POST } from '../links';

// Records the dismissal client-side so the preview card stays swapped out
const PREVIEW_DISMISS_COOKIE = 'devhub-preview-banner-dismissed';
const DISMISS_MAX_AGE = 60 * 60 * 24 * 365;

const hasDismissed = (cookie: string): boolean =>
  document.cookie.split('; ').some((entry) => entry === `${cookie}=1`);

const recordDismissal = (cookie: string): void => {
  // biome-ignore lint/suspicious/noDocumentCookie: cookieStore API is https only, but local dev is http
  document.cookie = `${cookie}=1; path=/; max-age=${DISMISS_MAX_AGE}; samesite=strict`;
};

@customElement('devhub-home-banner')
export class DevhubHomeBanner extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    moz-page-header {
      display: block;
      margin-block: var(--space-xxlarge);
    }
    .preview-banner {
      margin-block: 1em;
      height: 200px;
    }
    #preview-banner-card::part(card) {
      padding-inline-start: 80px;
    }
    .preview-banner-content {
      display: flex;
      align-items: center;
      gap: var(--space-large);
    }
    .preview-banner-text {
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: var(--space-small);
    }
    .preview-banner-header {
      font-size: 26px;
      font-weight: 590;
    }
    .preview-banner-message a {
      text-decoration: none;
    }
    moz-illustration {
      flex: none;
      width: 154px;
    }
    .preview-banner-dismiss {
      flex: none;
      align-self: flex-start;
    }
  `;

  @state() private previewDismissed = hasDismissed(PREVIEW_DISMISS_COOKIE);

  #dismissPreview = () => {
    recordDismissal(PREVIEW_DISMISS_COOKIE);
    this.previewDismissed = true;
  };

  render() {
    // Once dismissed, fall back to the plain page header in place of the card.
    if (this.previewDismissed) {
      return html`<moz-page-header
        heading="Welcome to the Developer Hub."
        description="Manage your Firefox add-ons, track reviews, and publish updates."
      ></moz-page-header>`;
    }
    return html`<div class="preview-banner">
      <moz-card id="preview-banner-card" heading="" spacing="default" appearance="default">
        <div class="preview-banner-content">
          <div class="preview-banner-text">
            <div class="preview-banner-header">
              You’re previewing the new Developer Hub
            </div>
            <div class="preview-banner-message">
              It’s still a work in progress.
              The workflow for building and managing add-ons will stay the same, but we’ll
              gradually roll out features with the new design.
              The previous version is still available.
              <a href="${PREVIEW_BLOG_POST}" target="external">Learn more</a>
            </div>
          </div>
          <moz-illustration name="pic-star-flame" label=""></moz-illustration>
          <moz-button
            class="preview-banner-dismiss"
            variant="ghost"
            icon-only="Dismiss"
            icon-start="close"
            @click=${this.#dismissPreview}
          ></moz-button>
        </div>
      </moz-card>
    </div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-home-banner': DevhubHomeBanner;
  }
}
