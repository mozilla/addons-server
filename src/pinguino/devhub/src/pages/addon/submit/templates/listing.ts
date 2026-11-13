import { html, nothing } from 'lit';
import { customElement, property, query } from 'lit/decorators.js';
import type { ListingDetailsCard } from '../../../../components/addon-listing/listing-details-card';
import { localized } from '../../../../data/api';
import {
  addonQuery,
  uploadQuery,
  uploadVersionSource,
} from '../../../../data/queries';
import { ADDON_STATUS } from '../../../../data/statuses';
import type {
  Addon,
  AddonKind,
  FileUpload,
  Version,
} from '../../../../data/types';
import { SubmissionStep } from '../submission-step';
import '../../../../components/addon-listing/listing-details-card';

function newAddon(kind: AddonKind, upload?: FileUpload): Addon {
  const manifest = upload?.manifest_data;
  return {
    slug: '',
    kind,
    icon: kind === 'theme' ? 'themes' : 'extension',
    name: localized(manifest?.name ?? undefined),
    summary: localized(manifest?.summary ?? undefined),
    homepageUrl: localized(manifest?.homepage ?? undefined),
    status: ADDON_STATUS.incomplete,
    version: '',
    lastUpdated: '',
    visibility: 'visible',
    canChangeVisibility: false,
  };
}

@customElement('submit-listing')
export class SubmitListing extends SubmissionStep {
  @property() slug = '';
  @property({ type: Number }) versionId?: number;
  @property() upload?: string;
  @property({ attribute: false }) source?: File;
  @property() kind: AddonKind = 'extension';

  @query('listing-details-card') private card?: ListingDetailsCard;

  #addon = addonQuery(this, () => this.slug);
  #upload = uploadQuery(this, () => (this.slug ? '' : (this.upload ?? '')));
  #created?: { slug: string; versionId: number; source?: File };

  protected get ready() {
    return Boolean(this.#listingAddon());
  }

  #listingAddon() {
    if (this.slug) return this.#addon().data;
    const upload = this.#upload();
    if (upload.isPending) return undefined;
    return newAddon(this.kind, upload.data);
  }

  async submit(): Promise<boolean> {
    if (!(await this.card?.save())) return false;
    const created = this.#created;
    this.#created = undefined;
    if (created?.source) {
      await uploadVersionSource(
        created.slug,
        created.versionId,
        created.source,
      ).catch(() => {});
    }
    return true;
  }

  render() {
    const addon = this.#listingAddon();
    if (!addon) return nothing;
    return html`
      <listing-details-card
        edit-only
        embedded
        .addon=${addon}
        .versionId=${this.versionId}
        .upload=${this.versionId ? undefined : this.upload}
        ?new-version=${Boolean(this.slug)}
        @addon-create=${(
          e: CustomEvent<{ addon: Addon; version: Version }>,
        ) => {
          const { addon, version } = e.detail;
          this.#created = {
            slug: addon.slug,
            versionId: version.id,
            source: this.source,
          };
        }}
        @version-create=${(
          e: CustomEvent<{ slug: string; version: Version }>,
        ) => {
          const { slug, version } = e.detail;
          this.#created = {
            slug,
            versionId: version.id,
            source: this.source,
          };
        }}
      ></listing-details-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'submit-listing': SubmitListing;
  }
}
