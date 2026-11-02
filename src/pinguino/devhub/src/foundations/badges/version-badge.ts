import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { type FileStatus, resolveVersionStatus } from '../../data';

@customElement('version-badge')
export class VersionBadge extends LitElement {
  @property() status: FileStatus = 'unreviewed';
  @property({ type: Boolean, attribute: 'user-disabled' }) userDisabled = false;
  @property() reviewed?: string | null;

  static styles = css`
    :host {
      display: contents;
    }
  `;

  render() {
    const { label, badge } = resolveVersionStatus(this.status, {
      isDisabled: this.userDisabled,
      reviewed: this.reviewed,
    });
    return html`<moz-status-badge type=${badge}>${label}</moz-status-badge>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'version-badge': VersionBadge;
  }
}
