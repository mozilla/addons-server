import { html } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { updateAddon } from '../../data';
import { SectionCard } from './section-card';

@customElement('technical-details-card')
export class TechnicalDetailsCard extends SectionCard {
  // Only developer comments are editable here; it's an add-on PATCH field.
  @state() private developerComments = '';

  #startEdit() {
    this.developerComments = this.addon.developerComments ?? '';
    this.error = '';
    this.editing = true;
  }

  async #save() {
    const next = this.developerComments;
    if (next === (this.addon.developerComments ?? '')) {
      this.editing = false;
      return;
    }
    this.saving = true;
    this.error = '';
    try {
      await updateAddon(this.addon.slug, { developerComments: next });
      this.editing = false;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Could not save changes.';
    } finally {
      this.saving = false;
    }
  }

  render() {
    const a = this.addon;
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="technical-details"
    >
      ${this.cardHead(
        'technical-details',
        this.draftActions(
          () => this.#startEdit(),
          () => this.#save(),
        ),
      )}
      ${
        this.editing
          ? html`<div class="form">
            ${this.errorBar()}
            <moz-textarea
              label="Developer comments"
              full-width
              .value=${this.developerComments}
              @input=${(e: Event) => {
                this.developerComments = (
                  e.target as HTMLTextAreaElement
                ).value;
              }}
            ></moz-textarea>
            <dl>
              ${this.row('UUID', a.uuid)} ${this.row('Whiteboard', a.whiteboard)}
            </dl>
          </div>`
          : html`<dl>
            ${this.row('Developer comments', a.developerComments)}
            ${this.row('UUID', a.uuid)} ${this.row('Whiteboard', a.whiteboard)}
          </dl>`
      }
    </moz-card>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'technical-details-card': TechnicalDetailsCard;
  }
}
