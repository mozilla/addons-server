import { html, nothing } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import {
  type Addon,
  type AddonScreenshot,
  createPreview,
  removePreview,
  updateIcon,
  updatePreview,
} from '../../data';
import { SectionCard } from './section-card';

@customElement('graphic-assets-card')
export class GraphicAssetsCard extends SectionCard {
  // In-progress screenshot caption edits, keyed by preview id.
  @state() private captionDrafts: Record<number, string> = {};

  // moz-input-file exposes the selection as a File[] (native inputs a FileList);
  // both index the same way.
  #firstFile(e: Event): File | undefined {
    const target = e.target as { files?: ArrayLike<File> | null };
    return target.files?.[0];
  }

  #onIcon(e: Event) {
    const file = this.#firstFile(e);
    if (file) this.runAction(() => updateIcon(this.addon.slug, file));
  }

  #onScreenshot(e: Event) {
    const file = this.#firstFile(e);
    if (file) this.runAction(() => createPreview(this.addon.slug, file));
  }

  #startEdit() {
    this.captionDrafts = {};
    this.error = '';
    this.editing = true;
  }

  // Edit / Save+Cancel. Caption edits are batched and persisted on Save;
  // icon/screenshot uploads stay immediate (a file picker commits on choice).
  #actions() {
    return this.editing
      ? html`<div class="card-actions">
          <moz-button
            size="small"
            variant="ghost"
            ?disabled=${this.saving}
            @click=${() => {
              this.editing = false;
              this.captionDrafts = {};
            }}
            >Cancel</moz-button
          >
          <moz-button
            size="small"
            variant="primary"
            ?disabled=${this.saving}
            @click=${() => this.#save()}
            >${this.saving ? 'Saving…' : 'Save'}</moz-button
          >
        </div>`
      : html`<moz-button size="small" @click=${() => this.#startEdit()}
          >Edit</moz-button
        >`;
  }

  // Persist the screenshot captions the user changed, then leave edit mode.
  async #save() {
    const slug = this.addon.slug;
    this.saving = true;
    this.error = '';
    try {
      for (const s of this.addon.screenshots ?? []) {
        if (s.id == null) continue;
        const draft = this.captionDrafts[s.id];
        if (draft !== undefined && draft !== (s.caption ?? '')) {
          await updatePreview(slug, s.id, draft);
        }
      }
      this.editing = false;
      this.captionDrafts = {};
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Could not save changes.';
    } finally {
      this.saving = false;
    }
  }

  #iconBox(px: number) {
    const a = this.addon;
    const inner = a.iconUrl
      ? html`<img
          src=${a.iconUrl}
          alt=""
          style="width:${px}px;height:${px}px;border-radius:4px"
        />`
      : undefined;
    return html`<div class="icon-box">
      <div class="frame" style="width:${px + 16}px;height:${px + 16}px">
        ${inner}
      </div>
      ${px}×${px}px
    </div>`;
  }

  // One screenshot row: thumbnail on the left, caption on the right — read-only
  // text when viewing, a labelled textarea when editing. Caption edits are held
  // in captionDrafts and saved by the card's Save button.
  #shot(a: Addon, s: AddonScreenshot) {
    const id = s.id;
    if (!this.editing) {
      return html`<div class="shot">
        <img src=${s.src} alt=${s.caption ?? ''} />
        <div class="shot-body">
          <p class="shot-caption ${s.caption ? '' : 'muted'}">
            ${s.caption || 'No caption'}
          </p>
        </div>
      </div>`;
    }
    const caption =
      id != null ? (this.captionDrafts[id] ?? s.caption ?? '') : '';
    return html`<div class="shot">
      <img src=${s.src} alt=${s.caption ?? ''} />
      <div class="shot-body">
        <p class="caption-label">
          Please provide a caption for this screenshot:
          <span class="locale-badge">English (US)</span>
        </p>
        <moz-textarea
          aria-label="Caption"
          placeholder="Text"
          full-width
          ?disabled=${id == null}
          .value=${caption}
          @input=${(e: Event) => {
            if (id == null) return;
            this.captionDrafts = {
              ...this.captionDrafts,
              [id]: (e.target as HTMLTextAreaElement).value,
            };
          }}
        ></moz-textarea>
        ${
          id != null
            ? html`<moz-button
              class="shot-remove"
              size="small"
              variant="ghost"
              ?disabled=${this.saving}
              @click=${() => this.runAction(() => removePreview(a.slug, id))}
              >Remove screenshot</moz-button
            >`
            : nothing
        }
      </div>
    </div>`;
  }

  render() {
    const a = this.addon;
    const shots = a.screenshots ?? [];
    return html`<moz-card
      appearance="outline"
      spacing="spacious"
      id="graphic-assets"
    >
      ${this.cardHead('graphic-assets', this.#actions())}
      <div class="asset">
        <p class="label">Upload an icon</p>
        <p class="help">
          You can upload PNG or JPG files. If your icon's bigger than 128×128
          pixels, we'll resize it for you. It will also scale to three sizes:
          32×32px, 64×64px, 128×128px.
        </p>
        <div class="icon-sizes">
          ${[32, 64, 128].map((px) => this.#iconBox(px))}
        </div>
        ${
          this.editing
            ? html`<moz-input-file
              accept="image/png,image/jpeg"
              label="Upload icon"
              ?disabled=${this.saving}
              @change=${(e: Event) => this.#onIcon(e)}
            ></moz-input-file>`
            : nothing
        }
      </div>
      <!-- Banner/hero assets are in the design but have no AMO API for
           extensions yet, so that section is omitted. -->
      <div class="asset">
        <p class="label">Screenshots</p>
        <p class="help">
          We support PNG and JPG, but PNG is best. Screenshots should be up to
          2400×1800 pixels. Adding screenshots to your product page really boosts
          the chances people will install it.
        </p>
        ${
          shots.length
            ? html`<div class="shots">
              ${shots.map((s) => this.#shot(a, s))}
            </div>`
            : html`<p class="muted">No screenshots uploaded yet.</p>`
        }
        ${
          this.editing
            ? html`<moz-input-file
              accept="image/png,image/jpeg"
              label="Upload screenshot"
              ?disabled=${this.saving}
              @change=${(e: Event) => this.#onScreenshot(e)}
            ></moz-input-file>`
            : nothing
        }
      </div>
      ${this.errorBar()}
    </moz-card>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'graphic-assets-card': GraphicAssetsCard;
  }
}
