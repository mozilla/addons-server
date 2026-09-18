import { css, html, LitElement, type PropertyValues } from 'lit';
import { customElement, property } from 'lit/decorators.js';

// A responsive column grid, container-query based (named `app-grid`).
//
// - Children size themselves with `grid-column: span N`.
// - Steps down at the md (768px) and sm (480px) container widths. By default a
//   step with no override collapses to a single column at md (and sm follows md);
//   set columns-md / columns-sm to keep intermediate steps, e.g.
//   columns="4" columns-md="2" columns-sm="1".
// - When a step resolves to a single column, children's spans are neutralized so
//   each item fills the row; otherwise a leftover `grid-column: span N` creates
//   phantom tracks + their gaps and the item comes up short.
// - It's a named container, so a consumer can reorder or re-span its own items at
//   these widths with `@container app-grid (max-width: …) { … }` in its styles.
@customElement('app-grid')
export class AppGrid extends LitElement {
  @property({ type: Number }) columns = 12;
  @property({ type: Number, attribute: 'columns-md' }) columnsMd?: number;
  @property({ type: Number, attribute: 'columns-sm' }) columnsSm?: number;

  static styles = css`
    :host {
      display: block;
      container: app-grid / inline-size;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(var(--_columns, 12), minmax(0, 1fr));
      gap: var(--space-large);
    }
    :host([gap='small']) .grid {
      gap: var(--space-small);
    }
    :host([gap='medium']) .grid {
      gap: var(--space-medium);
    }
    :host([gap='xlarge']) .grid {
      gap: var(--space-xlarge);
    }

    @container app-grid (max-width: 768px) {
      .grid {
        grid-template-columns: repeat(var(--_columns-md, 1), minmax(0, 1fr));
      }
      :host([data-stack-md]) ::slotted(*) {
        grid-column: auto !important;
      }
    }
    @container app-grid (max-width: 480px) {
      .grid {
        grid-template-columns: repeat(var(--_columns-sm, 1), minmax(0, 1fr));
      }
      :host([data-stack-sm]) ::slotted(*) {
        grid-column: auto !important;
      }
    }
  `;

  protected updated(changed: PropertyValues<this>) {
    if (
      changed.has('columns') ||
      changed.has('columnsMd') ||
      changed.has('columnsSm')
    ) {
      // No override means break to a single column at md; sm follows md.
      const md = this.columnsMd ?? 1;
      const sm = this.columnsSm ?? this.columnsMd ?? 1;
      this.style.setProperty('--_columns', String(this.columns));
      this.style.setProperty('--_columns-md', String(md));
      this.style.setProperty('--_columns-sm', String(sm));
      this.toggleAttribute('data-stack-md', md === 1);
      this.toggleAttribute('data-stack-sm', sm === 1);
    }
  }

  render() {
    return html`<div class="grid"><slot></slot></div>`;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'app-grid': AppGrid;
  }
}
