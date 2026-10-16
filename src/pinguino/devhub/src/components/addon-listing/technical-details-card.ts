import { html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { updateAddon } from '../../data';
import { FormController, textArea } from '../../foundations/form';
import { SectionCard } from './section-card';

type TechnicalDraft = { developer_comments?: string };

@customElement('technical-details-card')
export class TechnicalDetailsCard extends SectionCard {
  #form = new FormController<TechnicalDraft>(this);

  #startEdit() {
    this.#form.start({
      developer_comments: this.addon.developerComments ?? '',
    });
  }

  #save() {
    return this.#form.submit(async (d) => {
      if (
        (d.developer_comments ?? '') === (this.addon.developerComments ?? '')
      ) {
        return;
      }
      await updateAddon(this.addon.slug, {
        developer_comments: d.developer_comments,
      });
    });
  }

  render() {
    const a = this.addon;
    const form = this.#form;
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="technical-details"
    >
      ${this.cardHead(
        'technical-details',
        this.draftActions(
          form,
          () => this.#startEdit(),
          () => this.#save(),
        ),
      )}
      ${
        form.editing
          ? html`<div class="form">
            ${this.errorBar(form.error)}
            ${textArea(form, 'developer_comments', 'Developer comments')}
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
