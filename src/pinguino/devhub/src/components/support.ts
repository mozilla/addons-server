import { css, html, LitElement, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { postSupport, type SupportCategory } from '../data/api';
import { FormController, textArea, textField } from '../foundations/form';

interface SupportDraft {
  category: SupportCategory | undefined;
  summary: string;
  body: string;
}

const EMPTY: SupportDraft = { category: undefined, summary: '', body: '' };

@customElement('support-form')
export class Support extends LitElement {
  static styles = css`
    :host {
      display: block;
      padding: var(--space-large);
    }

    .layout {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-xlarge);
      align-items: flex-start;
    }

    .illustration {
      flex: 0 0 auto;
      width: 200px;
    }

    form {
      flex: 1 1 600px;
      max-width: 600px;
    }

    moz-fieldset {
      width: 100%;
    }

    moz-fieldset::part(legend) {
      font-size: var(--font-size-xlarge);
    }
  `;

  #form = new FormController<SupportDraft>(this);
  @state() private sent = false;

  connectedCallback() {
    super.connectedCallback();
    this.#form.start({ ...EMPTY });
  }

  async #onSubmit(event: SubmitEvent) {
    event.preventDefault();
    await this.#form.submit(async (draft) => {
      await postSupport({
        category: draft.category as SupportCategory,
        summary: draft.summary,
        body: draft.body,
      });
      this.sent = true;
      // Clear the inputs so the form is ready for another request.
      this.#form.start({ ...EMPTY });
    });
  }

  render() {
    const { saving, error } = this.#form;
    return html`
    ${
      this.sent
        ? html`<moz-message-bar type="success"
            >Your support request has been submitted. We will be in touch soon.</moz-message-bar
          >`
        : nothing
    }
    ${
      error
        ? html`<moz-message-bar type="error">${error}</moz-message-bar>`
        : nothing
    }

    <div class="layout">
    <moz-illustration class="illustration" name="kit-closeup-look-forward" label=""></moz-illustration>

    <form @submit=${this.#onSubmit}>
      <moz-fieldset
        label="Get support for extensions and themes"
        description="Use this form for support related to your account, policy compliance issues and more.
      The more details you share, the easier it is for us to help.
      For questions about your add-on(s) reviews, please refer to your add-on(s) version history.
      We'll get back to you as soon as possible."
      >
      ${textField(this.#form, 'summary', 'Subject', 'text', 'Summarise the issue in a few words')}

      <moz-select
          label="Select category"
          name="category"
          variant="standard"
          size="default"
          popup="native"
          placeholder="Choose a category"
          error=${this.#form.fieldError('category')}
          .value=${this.#form.value('category')}
          @change=${(e: Event) =>
            this.#form.set(
              'category',
              (e.target as HTMLSelectElement).value as SupportCategory,
            )}
        >
          <moz-option value="policy" label="Technical support for making your add-on compliant"></moz-option>
          <moz-option value="technical" label="Issue with addons.mozilla.org"></moz-option>
          <moz-option value="other" label="Other"></moz-option>
        </moz-select>


        ${textArea(
          this.#form,
          'body',
          'Describe the issue',
          'Give us more details about the issue',
          10000,
          8,
        )}

        <moz-button variant="default" size="medium" type="submit" ?disabled=${saving}>
          ${saving ? 'Sending…' : 'Send request'}
        </moz-button>
      </moz-fieldset>
    </form>
    </div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'support-form': Support;
  }
}
