import type { IconName, MozPanelList } from '@mozilla/lit-web-components';
import { css, html, LitElement, nothing, type TemplateResult } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { BASE, LOCALE } from '../base';
import { type Addon, navAddonsQuery, profileQuery } from '../data';
import { panelPointer } from '../foundations/panel';
import {
  ADDONS_BLOG,
  ADDONS_FORUM,
  extensionWorkshop,
  PREVIEW_BLOG_POST,
} from '../links';
import './devhub-account-menu';
import './switch-back-link';

interface NavItem {
  label: string;
  href: string;
  external?: boolean;
  icon?: IconName;
}

// A captioned run of rows. A menu is one or more, separated by a rule — the
// unit the collapsed menu concatenates.
interface NavSection {
  label: string;
  items: NavItem[];
}

interface NavMenu {
  /** Scoped to this shadow root; moz-button resolves it via getRootNode(). */
  id: string;
  label: string;
  sections: NavSection[];
}

// Past this the menu stops being a menu, so the rest live on the dashboard.
const MAX_ADDONS = 7;

// Long enough to cross the gap between a trigger and its menu.
const HOVER_CLOSE_DELAY = 200;

// Every menu but My Add-ons is a single captioned run of rows.
const menu = (id: string, label: string, items: NavItem[]): NavMenu => ({
  id,
  label,
  sections: [{ label, items }],
});

const MENUS: NavMenu[] = [
  menu('nav-documentation', 'Documentation & Support', [
    {
      label: 'Extension Development',
      href: extensionWorkshop('/documentation/develop/'),
      external: true,
    },
    {
      label: 'Themes',
      href: extensionWorkshop('/documentation/themes/'),
      external: true,
    },
    {
      label: 'Developer Add-on Policies',
      href: extensionWorkshop('/documentation/publish/add-on-policies/'),
      external: true,
    },
    {
      label: 'Publishing Guide',
      href: extensionWorkshop('/documentation/publish/'),
      external: true,
    },
    { label: 'Add-on Blog', href: ADDONS_BLOG, external: true },
    { label: 'Add-on Forum', href: ADDONS_FORUM, external: true },
    { label: 'Contact Support', href: `${BASE}/support` },
  ]),
  menu('nav-tools', 'Tools', [
    { label: 'Add-on Validator', href: `${BASE}/addon/validate` },
  ]),
];

// Starts the FxA login flow, returning the user to `path` afterwards.
const loginUrl = (path: string) =>
  `/api/v5/accounts/login/start/?to=${encodeURIComponent(path)}`;

@customElement('devhub-header')
export class DevhubHeader extends LitElement {
  static styles = [
    panelPointer,
    css`
      :host {
        display: block;
        background-color: var(--background-color-box);
      }
      .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--space-large);
        padding-block: var(--space-large);
        padding-inline: var(--space-large) var(--space-xlarge);
      }
      .start {
        display: flex;
        align-items: center;
        gap: var(--space-small);
      }
      .preview {
        display: flex;
      }
      .preview moz-badge {
        font-size: var(--font-size-small);
        block-size: var(--icon-size-medium);
      }
      .brand {
        display: flex;
        align-items: center;
        gap: var(--space-small);
        padding-inline-start: var(--space-small);
        color: var(--text-color, CanvasText);
        font-size: var(--font-size-heading-large);
        font-weight: 600;
        text-decoration: none;
      }
      .brand moz-icon {
        --icon-size: 40px;
      }
      nav {
        display: flex;
        align-items: center;
        /* The design spaces labels 32px apart; the triggers contribute 8px of
         * padding each so they have a hit area wider than their text. */
        gap: var(--space-large);
      }
      /* A second row would push the bar off the design's height; the
       * breakpoint below is what keeps it to one. */
      nav.full {
        flex-wrap: nowrap;
      }
      .drawer-button {
        display: none;
      }
      /* Measured: signed in, the brand, menus, switch-back link and avatar need
       * 1032px before they collide. */
      @media (max-width: 1040px) {
        nav.full {
          display: none;
        }
        .drawer-button {
          display: inline-flex;
        }
      }
      .drawer::part(dialog) {
        position: fixed;
        inset-block: 0;
        inset-inline-start: 0;
        margin: 0;
        inline-size: min(320px, 100vw - var(--space-xxlarge));
        max-inline-size: none;
        block-size: 100dvh;
        max-block-size: 100dvh;
        border-radius: 0;
        overflow-y: auto;
        animation: drawer-in 200ms ease-out;
      }
      .drawer:dir(rtl)::part(dialog) {
        animation-name: drawer-in-rtl;
      }
      @keyframes drawer-in {
        from {
          transform: translateX(-100%);
        }
      }
      @keyframes drawer-in-rtl {
        from {
          transform: translateX(100%);
        }
      }
      @media (prefers-reduced-motion: reduce) {
        .drawer::part(dialog) {
          animation: none;
        }
      }
      .drawer h3 {
        margin: var(--space-small) 0 var(--space-xsmall);
        font-size: var(--font-size-small);
        font-weight: 600;
        color: var(--text-color-deemphasized);
      }
      .drawer ul {
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .drawer li a {
        display: flex;
        align-items: center;
        gap: var(--space-small);
        padding: var(--space-small);
        border-radius: var(--border-radius-medium);
      }
      .drawer li a:hover {
        background: var(--button-background-color-ghost-hover);
        text-decoration: none;
      }
      .drawer li a .external {
        margin-inline-start: auto;
      }
      .drawer switch-back-link {
        display: block;
        margin-block-start: var(--space-large);
      }
      .trigger::part(button) {
        padding-inline: var(--space-small);
        font-weight: 400;
      }
      a,
      ::part(link) {
        color: var(--text-color, CanvasText);
        text-decoration: none;
        font-size: var(--font-size-root);
      }
      a:hover,
      ::part(link):hover {
        text-decoration: underline;
      }
      /* Holds the row's height steady while the profile loads, so the bar doesn't
       * jump when the avatar replaces the log-in link. */
      .account {
        display: flex;
        align-items: center;
        justify-content: flex-end;
        min-block-size: var(--size-item-large);
      }
    `,
  ];

  // Signed-in developer, session-lived. data present => signed in; no data (and
  // not loading) => signed out, since the profile can't be fetched without a
  // session.
  #profile = profileQuery(this);

  // One past what the menu lists, which is how we know to offer "More".
  #addons = navAddonsQuery(this, MAX_ADDONS + 1, () =>
    Boolean(this.#profile().data),
  );

  // Navigate to the login flow, using the current location.
  #login = (event: Event) => {
    event.preventDefault();
    location.href = loginUrl(location.pathname + location.search);
  };

  #loginLink() {
    // href carries the return path for no-JS / copy / middle-click
    return html`<a
      class="login"
      href="${loginUrl(location.pathname + location.search)}"
      @click=${this.#login}
      >Log in</a
    >`;
  }

  #trigger(id: string, label: string) {
    return html`<moz-button
      class="trigger"
      variant="ghost"
      icon-end="chevron-down"
      menu-id=${id}
      @pointerenter=${(e: PointerEvent) => this.#hoverOpen(e, id)}
      @pointerleave=${this.#hoverLeave}
      @click=${{
        // Runs before moz-button's own toggle, which would shut a menu the
        // hover just opened.
        handleEvent: (e: Event) => {
          if (this.#hovered === id) e.stopPropagation();
        },
        capture: true,
      }}
      >${label}</moz-button
    >`;
  }

  #item({ label, href, external, icon }: NavItem) {
    return html`<moz-panel-item
      href=${href}
      icon-start=${icon ?? nothing}
      target=${external ? '_blank' : nothing}
      icon-end=${external ? 'external-link' : nothing}
      >${label}</moz-panel-item
    >`;
  }

  // Rules go between sections, never before the first, so a single-section
  // menu still reads as one list.
  #sections(sections: NavSection[]) {
    return sections.map(
      (section, i) => html`
        ${i > 0 ? html`<hr />` : nothing}
        <h2>${section.label}</h2>
        ${section.items.map((item) => this.#item(item))}
      `,
    );
  }

  #menu({ id, label, sections }: NavMenu): TemplateResult {
    return html`
      ${this.#trigger(id, label)}
      <moz-panel-list
        id=${id}
        type="menu"
        label=${label}
        @pointerenter=${(e: PointerEvent) => {
          if (e.pointerType === 'mouse') clearTimeout(this.#hoverTimer);
        }}
        @pointerleave=${this.#hoverLeave}
        @moz-panel-list:hidden=${() => {
          if (this.#hovered === id) this.#hovered = undefined;
        }}
      >
        ${this.#sections(sections)}
      </moz-panel-list>
    `;
  }

  #hovered?: string;
  #hoverTimer?: ReturnType<typeof setTimeout>;

  #panel(id: string) {
    return this.renderRoot.querySelector<MozPanelList>(`#${id}`);
  }

  #hoverOpen(e: PointerEvent, id: string) {
    if (e.pointerType !== 'mouse') return;
    clearTimeout(this.#hoverTimer);
    if (this.#hovered && this.#hovered !== id) {
      this.#panel(this.#hovered)?.hide();
    }
    const panel = this.#panel(id);
    // Given the pointerenter, the panel doesn't move focus into itself.
    if (!panel?.open) panel?.show(e, e.currentTarget as HTMLElement);
    this.#hovered = id;
  }

  #hoverLeave = (e: PointerEvent) => {
    const id = this.#hovered;
    if (e.pointerType !== 'mouse' || !id) return;
    this.#hoverTimer = setTimeout(
      () => this.#panel(id)?.hide(),
      HOVER_CLOSE_DELAY,
    );
  };

  disconnectedCallback() {
    super.disconnectedCallback();
    clearTimeout(this.#hoverTimer);
  }

  // The signed-in developer's own menu, as data so both layouts render it the
  // same way. Sorted by name to match the classic devhub's my_addons().
  #myAddons(): NavMenu {
    const addons: Addon[] = [...(this.#addons().data ?? [])].sort((a, b) =>
      a.name.localeCompare(b.name, LOCALE ?? undefined),
    );
    const listed: NavItem[] = addons.slice(0, MAX_ADDONS).map((addon) => ({
      label: addon.name,
      href: `${BASE}/addon/${addon.slug}`,
      icon: addon.kind === 'theme' ? 'themes' : 'extension',
    }));
    if (addons.length > MAX_ADDONS) {
      listed.push({ label: 'More add-ons\u2026', href: `${BASE}/` });
    }
    return {
      id: 'nav-my-addons',
      label: 'My Add-ons',
      sections: [
        { label: 'My Add-ons', items: listed },
        {
          label: 'Create New Add-on',
          items: [
            {
              label: 'Submit a New Add-on',
              href: `${BASE}/addon/submit/agreement`,
            },
            {
              label: 'Submit a New Theme',
              href: `${BASE}/addon/submit/theme/agreement`,
            },
          ],
        },
      ],
    };
  }

  @state() private drawerOpen = false;
  // Closed by default and one at a time, so the drawer fits a short screen.
  @state() private drawerSection?: string;

  #drawerLink({ label, href, external, icon }: NavItem) {
    return html`<a
      href=${href}
      target=${external ? '_blank' : nothing}
      rel=${external ? 'noopener' : nothing}
      @click=${() => {
        this.drawerOpen = false;
      }}
    >
      ${icon ? html`<moz-icon name=${icon}></moz-icon>` : nothing} ${label}
      ${
        external
          ? html`<moz-icon class="external" name="external-link"></moz-icon>`
          : nothing
      }
    </a>`;
  }

  #drawer(menus: NavMenu[]) {
    return html`<moz-dialog
      class="drawer"
      heading="Menu"
      dismissable
      dismiss-label="Close menu"
      ?open=${this.drawerOpen}
      @moz-dialog:dismiss=${() => {
        this.drawerOpen = false;
      }}
    >
      ${menus.map(
        (menu) => html`<moz-details
          heading=${menu.label}
          ?open=${this.drawerSection === menu.id}
          @moz-details:toggle=${(e: CustomEvent<{ open: boolean }>) => {
            this.drawerSection = e.detail.open ? menu.id : undefined;
          }}
        >
          ${menu.sections.map(
            (section) => html`
              ${section.label === menu.label ? nothing : html`<h3>${section.label}</h3>`}
              <ul>
                ${section.items.map((item) => html`<li>${this.#drawerLink(item)}</li>`)}
              </ul>
            `,
          )}
        </moz-details>`,
      )}
      <switch-back-link>Switch back to the old Developer Hub</switch-back-link>
    </moz-dialog>`;
  }

  render() {
    const profile = this.#profile();
    const menus = profile.data ? [this.#myAddons(), ...MENUS] : MENUS;
    return html`
      <div class="bar">
        <div class="start">
          <moz-button
            class="drawer-button"
            variant="ghost"
            icon-start="app-menu"
            icon-only="Menu"
            @click=${() => {
              this.drawerOpen = true;
            }}
          ></moz-button>
          <a class="brand" href="${BASE}">
            <moz-icon name="logo-firefox"></moz-icon>
            Add-ons
          </a>
          <a class="preview" href="${PREVIEW_BLOG_POST}" target="external">
            <moz-badge type="new">Preview</moz-badge>
          </a>
        </div>
        <nav class="full">
          ${menus.map((menu) => this.#menu(menu))}
          <switch-back-link>Switch back to the old Developer Hub</switch-back-link>
        </nav>
        <span class="account">
          ${
            profile.isPending || !profile.data
              ? this.#loginLink()
              : html`<devhub-account-menu
                    .profile=${profile.data}
                  ></devhub-account-menu>`
          }
        </span>
      </div>
      ${this.#drawer(menus)}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-header': DevhubHeader;
  }
}
