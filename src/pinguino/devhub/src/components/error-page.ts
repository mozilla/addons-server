import type { IllustrationName } from '@mozilla/lit-web-components';
import { css, html, LitElement } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { BASE } from '../base';

interface ErrorCopy {
  heading: string;
  message: string;
  illustration: IllustrationName;
}

const BY_CODE: Record<number, ErrorCopy> = {
  401: {
    heading: 'Please sign in',
    message: 'You need to be signed in to your Firefox account to see this.',
    illustration: 'kit-hold-lock',
  },
  403: {
    heading: "You don't have access to this",
    message:
      "The page is fine, but your account just isn't allowed to open it. Check you're signed in as the right developer.",
    illustration: 'kit-hold-lock',
  },
  404: {
    heading: 'Page not found',
    message:
      "We're all about a healthy internet but sometimes broken URLs happen.",
    illustration: 'kit-alert-tail-exclamation',
  },
};

// Anything without its own entry falls back to the family, so an unmapped 502
// still blames the right side.
const BY_FAMILY: Record<number, ErrorCopy> = {
  4: {
    heading: "That request didn't work",
    message: 'Something about the request was off. Try again from the start.',
    illustration: 'kit-alert-tail-exclamation',
  },
  5: {
    heading: 'Something went wrong on our end',
    message:
      "This one's us, not you. Try again in a moment, and if it keeps happening, let us know.",
    illustration: 'kit-plug-error',
  },
};

const GENERIC: ErrorCopy = {
  heading: 'Something went wrong',
  message: "We couldn't load this page.",
  illustration: 'kit-alert-tail-exclamation',
};

export function errorCopy(code: number): ErrorCopy {
  return BY_CODE[code] ?? BY_FAMILY[Math.floor(code / 100)] ?? GENERIC;
}

/**
 * The full-page error view: a 404 by default, any other 4xx/5xx by `code`.
 *
 * Copy and artwork come from the status, so a caller that knows the real one
 * (`errorStatus(query.error)`) gets an accurate page for free.
 *
 * @slot actions - replaces the "Back to homepage" button — a retry, say.
 */
@customElement('error-page')
export class ErrorPage extends LitElement {
  /** HTTP status to present. */
  @property({ type: Number }) code = 404;

  /** Overrides the status's heading. */
  @property() heading?: string;

  /** Overrides the status's message. */
  @property() message?: string;

  static styles = css`
    :host {
      display: grid;
      /* Claims the height the header leaves, so centring lands in the middle of
       * the viewport rather than the middle of this page's own content. */
      flex: 1;
      align-content: center;
      box-sizing: border-box;
      padding-block: var(--space-xxlarge);
    }
    /* The copy never fills eight columns of a 1280px container, so the pair
     * would sit left of centre at full width. Capping the grid keeps the 4:8
     * ratio while letting the auto margins centre it. */
    app-grid {
      /* An explicit size, not max-inline-size: as a grid item the auto margins
       * would otherwise shrink this to its content instead of centring it. */
      inline-size: min(100%, 960px);
      margin-inline: auto;
    }
    .art {
      grid-column: span 4;
      justify-self: center;
    }
    .copy {
      grid-column: span 8;
    }
    /* Both tracks centre on each other, so a short message doesn't hang off the
     * top of a 300px illustration. */
    .art,
    .copy {
      align-self: center;
    }
    h1 {
      margin: 0;
      font-size: var(--font-size-heading-xlarge);
    }
    p {
      margin: 0;
      color: var(--text-color-deemphasized);
    }
    ::slotted(*),
    moz-button {
      align-self: start;
    }
  `;

  render() {
    const copy = errorCopy(this.code);
    return html`
      <app-grid columns="12">
        <div class="art">
          <moz-illustration name=${copy.illustration}></moz-illustration>
        </div>
        <app-stack class="copy" gap="large">
          <h1>${this.code}: ${this.heading ?? copy.heading}</h1>
          <p>${this.message ?? copy.message}</p>
          <slot name="actions">
            <moz-button href="${BASE}">Back to homepage</moz-button>
          </slot>
        </app-stack>
      </app-grid>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'error-page': ErrorPage;
  }
}
