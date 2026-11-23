import { css, html } from 'lit';

export const timelineStyles = css`
  .timeline {
    --marker-size: var(--space-xlarge);
    --timeline-inset: var(--space-medium);
    --step-gap: var(--space-xlarge);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .step {
    position: relative;
  }
  .step + .step {
    margin-top: var(--step-gap);
  }
  .step:has(+ .step)::after {
    content: '';
    position: absolute;
    width: 1px;
    background: var(--background-color-information);
    top: calc(var(--marker-size) + 2 * var(--space-small));
    bottom: calc(-1 * var(--step-gap));
    left: calc(var(--timeline-inset) + var(--marker-size) / 2);
  }
  .row {
    display: flex;
    align-items: flex-start;
    gap: var(--space-medium);
    padding: var(--space-small) var(--timeline-inset);
    box-sizing: border-box;
  }
`;

export function timelineStep(marker: unknown, content: unknown) {
  return html`<li class="step">
    <div class="row">${marker}${content}</div>
  </li>`;
}
