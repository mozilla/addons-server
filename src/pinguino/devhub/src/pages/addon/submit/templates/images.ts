import { html } from 'lit';
import { customElement, property, query } from 'lit/decorators.js';
import type { GraphicAssetsCard } from '../../../../components/addon-listing/graphic-assets-card';
import { addonQuery } from '../../../../data/queries';
import { SubmissionStep } from '../submission-step';
import '../../../../components/addon-listing/graphic-assets-card';

@customElement('submit-images')
export class SubmitImages extends SubmissionStep {
  @property() slug = '';

  @query('graphic-assets-card') private card?: GraphicAssetsCard;

  #addon = addonQuery(this, () => this.slug);

  protected get ready() {
    return Boolean(this.#addon().data);
  }

  async submit(): Promise<boolean> {
    return (await this.card?.save()) ?? false;
  }

  render() {
    const addon = this.#addon().data;
    return html`<graphic-assets-card
          edit-only
          embedded
          .addon=${addon}
        ></graphic-assets-card>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-images': SubmitImages;
  }
}
