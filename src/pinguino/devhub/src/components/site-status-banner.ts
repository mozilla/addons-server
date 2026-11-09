import { css, html, LitElement, nothing } from 'lit';
import { customElement } from 'lit/decorators.js';
import { profileQuery, siteStatusQuery } from '../data';

@customElement('site-status-banner')
export class SiteStatusBanner extends LitElement {
  static styles = css`
    :host {
      display: block;
    }
    .site-status {
      /* Inline margins come from the surrounding app-container so the banner
       * lines up with the page content; only vertical spacing is ours. */
      margin-block: 1em;
    }
    .site-status-content {
      display: flex;
      align-items: center;
      gap: var(--space-large);
    }
    .site-status-message {
      flex: 1;
      font-size: 18px;
      font-weight: 590;
    }
    moz-illustration {
      flex: none;
      width: 64px;
    }
  `;

  // Site status is included in the profile response. When that request fails
  // (signed out, or any other reason) - but only once the profile has
  // actually errored - we retry with the standalone site status query.
  #profile = profileQuery(this);
  #siteStatus = siteStatusQuery(this, () => this.#profile().isError);

  render() {
    // Prefer the status carried by the profile; fall back to the standalone query.
    const siteStatus =
      this.#profile().data?.siteStatus ?? this.#siteStatus().data;
    if (!siteStatus?.siteNotice && !siteStatus?.readOnly) {
      return nothing;
    }
    const message =
      siteStatus.siteNotice ||
      html`<p>Some features are temporarily disabled while we perform website maintenance.
      We'll be back to full capacity shortly.</p>`;
    return html`<div class="site-status">
      <moz-card id="site-status-card" heading="" spacing="default" appearance="default">
        <div class="site-status-content">
          <div class="site-status-message">${message}</div>
          <moz-illustration name="pic-shield-alert" label=""></moz-illustration>
        </div>
      </moz-card>
    </div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'site-status-banner': SiteStatusBanner;
  }
}
