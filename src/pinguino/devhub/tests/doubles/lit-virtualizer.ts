// Test double for `@lit-labs/virtualizer`. The real virtualizer measures DOM
// layout (ResizeObserver, slots) that happy-dom doesn't implement, so it renders
// nothing and throws under the test environment. This stub registers a
// `<lit-virtualizer>` that renders every item eagerly into its light DOM, so DOM
// assertions on the rendered rows behave as they would in a real browser. It is
// aliased in for `@lit-labs/virtualizer` by vitest.config.ts only.

import { html, LitElement, type TemplateResult } from 'lit';
import { property } from 'lit/decorators.js';

class LitVirtualizerStub extends LitElement {
  @property({ attribute: false }) items: unknown[] = [];
  @property({ attribute: false }) renderItem: (
    item: unknown,
    index: number,
  ) => TemplateResult = () => html``;

  // Render into light DOM so rows live in the host's shadow tree, matching the
  // real virtualizer and keeping `host.shadowRoot.querySelectorAll` working.
  createRenderRoot() {
    return this;
  }

  render() {
    return html`${(this.items ?? []).map((item, i) => this.renderItem(item, i))}`;
  }
}

if (!customElements.get('lit-virtualizer')) {
  customElements.define('lit-virtualizer', LitVirtualizerStub);
}
