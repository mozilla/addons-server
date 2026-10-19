import type { PropertyValues } from 'lit';
import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { classMap } from 'lit/directives/class-map.js';

export interface TimelineStep {
  label: string;
  href?: string;
}

export interface TimelineSection {
  title: string;
  steps: TimelineStep[];
}

@customElement('timeline-nav')
export class TimelineNav extends LitElement {
  static styles = css`
    nav {
      --marker-size: var(--space-xlarge);
      --marker-ring: var(--space-xsmall);
    }
    ol {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .title {
      margin: var(--space-medium);
      font: inherit;
      font-weight: bold;
    }
    .step {
      position: relative;
    }
    .step + .step {
      margin-top: var(--space-xlarge);
    }
    .step + .step::before {
      content: '';
      position: absolute;
      width: 1px;
      height: var(--space-xlarge);
      background: var(--background-color-information);
      bottom: 100%;
      left: calc(var(--space-medium) + var(--marker-size) / 2);
    }
    .row {
      display: flex;
      align-items: center;
      border: none;
      background: none;
      width: 100%;
      border-radius: var(--border-radius-large);
      color: var(--text-color-deemphasized);
      gap: var(--space-medium);
      padding: var(--space-small) var(--space-medium);
      box-sizing: border-box;
    }
    .marker {
      display: grid;
      place-items: center;
      box-sizing: border-box;
      border-radius: 50%;
      background: var(--color-gray-30);
      width: var(--marker-size);
      height: var(--marker-size);
      border: var(--marker-ring) solid var(--color-gray-10);
    }
    .marker moz-icon {
      width: 10px;
      height: 10px;
      color: var(--background-color-canvas);
    }
    .current .row {
      font-weight: 600;
      color: var(--text-color);
      background: var(--background-color-information);
    }
    .current .marker {
      background: var(--icon-color-information);
    }
    .completed .marker {
      background: var(--icon-color-success);
      border-color: var(--background-color-success);
    }
  `;

  @property({ attribute: false }) sections: TimelineSection[] = [];
  @property({ type: Boolean }) completed = false;
  @property({ type: Number }) currStep = 0;

  private get steps(): TimelineStep[] {
    return this.sections.flatMap((section) => section.steps);
  }

  willUpdate() {
    const path = window.location.pathname;
    if (this.steps[this.currStep]?.href === path) return;
    const i = this.steps.findIndex((s) => s.href === path);
    if (i >= 0) this.currStep = i;
  }

  updated(changed: PropertyValues) {
    if (!changed.has('currStep')) return;
    this.dispatchEvent(
      new CustomEvent('timeline-nav:change', {
        detail: { index: this.currStep },
      }),
    );
  }

  private renderStep({ label }: TimelineStep, i: number) {
    const completed = this.completed || i < this.currStep;
    const current = !this.completed && i === this.currStep;
    return html`
      <li class=${classMap({ step: true, completed, current })}>
        <div class="row">
          <span class="marker">
            <moz-icon name="checkmark" ?hidden=${!completed}></moz-icon>
          </span>
          ${label}
        </div>
      </li>
    `;
  }

  render() {
    let i = 0;
    return html`
      <moz-card>
        <nav>
          <ol>
            ${this.sections.map(
              ({ title, steps }) => html`
                <li class="title">${title}</li>
                ${steps.map((step) => this.renderStep(step, i++))}
              `,
            )}
          </ol>
        </nav>
      </moz-card>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'timeline-nav': TimelineNav;
  }
}
