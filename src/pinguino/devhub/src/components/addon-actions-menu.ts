import { css, html, LitElement, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { BASE } from '../base';
import {
  type Addon,
  addonOwnershipQuery,
  removeAddon,
  setAddonVisibility,
} from '../data';
import { routeApiError } from '../foundations/form';
import { navigateTo } from '../helper';

// moz-button resolves this through getRootNode(), so it stays scoped to this
// component's shadow root however many headers are on the page.
const MENU_ID = 'addon-actions';

type Confirm = 'disable' | 'enable' | 'delete';

/**
 * The manage header's overflow menu: disable/enable the listing, or delete the
 * add-on. Both are destructive enough to confirm first, so each opens a modal
 * before anything is sent.
 *
 * Once Mozilla has disabled or deleted the add-on neither action is the
 * author's to take, so the menu goes away with them.
 */
@customElement('addon-actions-menu')
export class AddonActionsMenu extends LitElement {
  @property({ attribute: false }) addon!: Addon;
  @state() private confirming?: Confirm;
  @state() private busy = false;
  @state() private error = '';

  #isOwner = addonOwnershipQuery(this, () => this.addon?.slug ?? '');

  // Transparent host, so the button is the flex item in the header's row.
  static styles = css`
    :host {
      display: contents;
    }
  `;

  get #hidden() {
    return this.addon.visibility === 'invisible';
  }

  #run(action: () => Promise<unknown>, onDone?: () => void) {
    this.busy = true;
    this.error = '';
    action()
      .then(() => {
        this.confirming = undefined;
        onDone?.();
      })
      .catch((e) => {
        const { error } = routeApiError(e);
        this.error = error || 'Something went wrong. Please try again.';
      })
      .finally(() => {
        this.busy = false;
      });
  }

  #confirm() {
    const { slug } = this.addon;
    if (this.confirming === 'delete') {
      // The add-on this page is about is gone, so leave the page with it.
      this.#run(
        () => removeAddon(slug),
        () => navigateTo(`${BASE}/`),
      );
    } else {
      this.#run(() =>
        setAddonVisibility(slug, this.#hidden ? 'visible' : 'invisible'),
      );
    }
  }

  get #dialog() {
    const { kind } = this.addon;
    if (this.confirming === 'delete') {
      return {
        heading: `Are you sure you want to delete your ${kind}?`,
        body: `Once deleted, it can be restored.`,
        action: `Delete ${kind}`,
      };
    }
    if (this.confirming === 'enable') {
      return {
        heading: `Are you sure you want disable your ${kind}?`,
        body: `Once enabled, you can disable it later`,
        action: `Enable ${kind}`,
      };
    }
    return {
      heading: `Are you sure you want disable your ${kind}?`,
      body: `Once disabled, you can enabled it later`,
      action: `Disable ${kind}`,
    };
  }

  #menu() {
    const { kind } = this.addon;

    return html`
      <moz-button
        size="large"
        variant="ghost"
        icon-start="page-actions"
        icon-only="Add-on actions"
        menu-id=${MENU_ID}
      ></moz-button>
      <moz-panel-list id=${MENU_ID} type="menu" label="Add-on actions">
        <moz-panel-item
          icon-start="block"
          @click=${() => {
            this.confirming = this.#hidden ? 'enable' : 'disable';
          }}
        >${this.#hidden ? `Enable ${kind}` : `Disable ${kind}`}</moz-panel-item>
        <moz-panel-item
          icon-start="delete"
          ?disabled=${!this.#isOwner()}
          description=${this.#isOwner() ? nothing : 'Only owners can delete an add-on.'}
          @click=${() => {
            // The row is disabled, but don't let a stray click open a dialog
            // whose only outcome would be a 403.
            if (this.#isOwner()) this.confirming = 'delete';
          }}
        >Delete ${kind}</moz-panel-item>
      </moz-panel-list>
    `;
  }

  render() {
    if (!this.addon.canChangeVisibility) return nothing;

    const { heading, body, action } = this.#dialog;
    return html`
      ${this.#menu()}
      <moz-dialog
        variant="modal"
        dismissable
        ?open=${this.confirming !== undefined}
        heading=${heading}
        @moz-dialog:dismiss=${() => {
          this.confirming = undefined;
          this.error = '';
        }}
      >
        ${body}
        ${
          this.error
            ? html`<moz-message-bar type="error">${this.error}</moz-message-bar>`
            : nothing
        }
        <moz-button slot="actions" data-dismiss ?disabled=${this.busy}>Cancel</moz-button>
        <moz-button slot="actions"
          variant=${this.confirming === 'delete' ? 'destructive' : 'primary'}
          ?disabled=${this.busy}
          @click=${() => this.#confirm()}
        >${action}</moz-button>
      </moz-dialog>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'addon-actions-menu': AddonActionsMenu;
  }
}
