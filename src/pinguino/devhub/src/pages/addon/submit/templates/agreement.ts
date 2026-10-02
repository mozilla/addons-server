import { css, html, LitElement } from 'lit';
import { customElement, query } from 'lit/decorators.js';
import { when } from 'lit/directives/when.js';
import { acceptAgreement, agreementQuery } from '../../../../data/queries';

const WORKSHOP_URL = 'https://extensionworkshop.com/documentation/publish';

@customElement('devhub-agreement')
export class DevhubAgreement extends LitElement {
  static styles = css`
  .form-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-small);
    padding: var(--space-small);
  }
  h3 {
    margin: 0;
  }
  `;

  @query('#display-name') private displayNameInput?: HTMLInputElement;
  #agreement = agreementQuery(this);
  #redirected = false;

  private redirect() {
    if (this.#redirected) return;
    this.#redirected = true;
    // TODO: Redirect
  }

  willUpdate() {
    this.#agreement().data?.has_read_developer_agreement && this.redirect();
  }

  private async onSubmit(event: SubmitEvent) {
    event.preventDefault();

    const data = this.#agreement().data;
    if (!data || this.#redirected) return;

    const displayName = this.displayNameInput?.value?.trim();
    await acceptAgreement({
      last_developer_agreement_change: data.last_developer_agreement_change,
      ...(displayName ? { display_name: displayName } : {}),
    });
    this.redirect();
  }

  private renderDisplayName() {
    return html`
    <div class="form-section">
      <h3>Display Name</h3>
      <div>
        Your account needs a display name set so users know who 
        your add-on is coming from. Please enter one below.
      </div>
    </div>

    <div class="form-section">
      <moz-input-text
      id="display-name"
      label="Display Name"
      required/>
    </div>
    `;
  }

  private renderForm() {
    return html`
      <form @submit=${this.onSubmit}>
      <div class="form-section" >
        <h3>Add-on Distribution Agreement</h3>
        <div>
          Before starting, please read and accept our Firefox Add-on
          Distribution Agreement, Review Policies and Rules and our
            <a href="${WORKSHOP_URL}/add-on-policies-faq"
            target="_blank" rel="noopener noreferrer">
            Frequently Asked Questions</a>.
          The Firefox Add-on Distribution Agreement also links to our 
          Privacy Notice which explains how we handle your information.
        </div>

        <ul class="agreement-links">
          <li>
            <a href="${WORKSHOP_URL}/firefox-add-on-distribution-agreement"
            target="_blank" rel="noopener noreferrer">
            Firefox Add-on Distribution Agreement</a>
          </li>
          <li>
            <a
              href="${WORKSHOP_URL}/add-on-policies"
              target="_blank"
              rel="noopener noreferrer"
              >Review Policies and Rules</a>
          </li>
        </ul>

        <moz-checkbox
          id="accept"
          label="I have read and accept this Agreement and the Rules and Policies."
          required>
        </moz-checkbox>
      </div>

        ${when(!this.#agreement().data?.display_name, () => this.renderDisplayName())}

      <div class="form-section">
        <div class="submit-buttons">
          <moz-button id="accept-agreement" type="submit" variant="primary">
            Accept
          </moz-button>
          or <a href="/pinguino/">Cancel</a>
        </div>
      </div>

      <div class="form-section">
          <a
            href="${WORKSHOP_URL}/developer-accounts/"
            >More information on Developer Accounts</a>
        </div>

      </form>
    `;
  }

  render() {
    return html`
    <moz-card>
      ${this.renderForm()}
    </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-agreement': DevhubAgreement;
  }
}
