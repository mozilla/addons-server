import type { IconName } from '@mozilla/lit-web-components';
import { css, html, LitElement, nothing, type TemplateResult } from 'lit';
import { customElement } from 'lit/decorators.js';
import { BASE, LOCALE } from '../base';
import { type Addon, allAddonsQuery, profileQuery } from '../data';
import { panelPointer } from '../foundations/panel';
import { ADDONS_BLOG, ADDONS_FORUM, extensionWorkshop } from '../links';
import { switchBackPath } from '../switch-back';
import './devhub-account-menu';

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

// Every menu but My Add-ons is a single captioned run of rows.
const menu = (id: string, label: string, items: NavItem[]): NavMenu => ({
  id,
  label,
  sections: [{ label, items }],
});

const MENUS: NavMenu[] = [
  menu('nav-documentation', 'Documentation', [
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
      label: 'Developer Policies',
      href: extensionWorkshop('/documentation/publish/add-on-policies/'),
      external: true,
    },
  ]),
  menu('nav-tools', 'Tools', [
    { label: 'Add-on Validator', href: `${BASE}/addon/validate` },
    { label: 'Manage API Keys', href: `${BASE}/addon/api/key` },
  ]),
  menu('nav-community', 'Community & Support', [
    { label: 'Add-on Blog', href: ADDONS_BLOG, external: true },
    { label: 'Add-on Forum', href: ADDONS_FORUM, external: true },
    { label: 'Contact Support', href: `${BASE}/support` },
  ]),
  // The design gives Extension Workshop a menu but doesn't say what's in it;
  // these mirror the site's own sections until UX fills the gap.
  menu('nav-workshop', 'Extension Workshop', [
    {
      label: 'Extension Workshop Home',
      href: extensionWorkshop(),
      external: true,
    },
    {
      label: 'Publishing Guide',
      href: extensionWorkshop('/documentation/publish/'),
      external: true,
    },
    {
      label: 'Managing Your Add-ons',
      href: extensionWorkshop('/documentation/manage/'),
      external: true,
    },
    {
      label: 'Get in Touch',
      href: extensionWorkshop('/', '#connect'),
      external: true,
    },
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
      nav.collapsed {
        display: none;
      }
      /* Measured: signed in, the brand, links and avatar need 1275px before they
       * collide. Below that everything folds into the one menu. */
      @media (max-width: 1280px) {
        nav.full {
          display: none;
        }
        nav.collapsed {
          display: flex;
        }
      }
      .trigger::part(button) {
        padding-inline: var(--space-small);
        font-weight: 400;
      }
      a {
        color: var(--text-color, CanvasText);
        text-decoration: none;
        font-size: var(--font-size-root);
      }
      a:hover {
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

  #addons = allAddonsQuery(this, () => Boolean(this.#profile().data));

  // Switch to the classic devhub via the Django endpoint that flips the PINGUINO
  // cookie; the bare href is a no-JS fallback (view defaults to the index).
  #switchToClassic = (event: Event) => {
    event.preventDefault();
    const path = switchBackPath();
    location.href = `${BASE}/switch-pinguino?path=${encodeURIComponent(path)}`;
  };

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
      <moz-panel-list id=${id} type="menu" label=${label}>
        ${this.#sections(sections)}
      </moz-panel-list>
    `;
  }

  // The signed-in developer's own menu, as data so both layouts render it the
  // same way. Sorted by name to match the classic devhub's my_addons().
  #myAddons(): NavMenu {
    const addons: Addon[] = [...this.#addons().data].sort((a, b) =>
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

  #switchBackLink() {
    // href carries the path for no-JS / copy / middle-click
    return html`<a
      rel="external"
      href="${BASE}/switch-pinguino"
      @click=${this.#switchToClassic}
      >Switch back to the old Developer Hub</a
    >`;
  }

  // Every menu's sections end to end behind one trigger. Flattened rather than
  // nested so each link stays one tap away.
  #collapsedNav(menus: NavMenu[]) {
    return html`
      <moz-button
        class="hamburger"
        variant="ghost"
        icon-start="app-menu"
        icon-only="Menu"
        menu-id="nav-collapsed"
      ></moz-button>
      <moz-panel-list id="nav-collapsed" type="menu" label="Menu">
        ${this.#sections(menus.flatMap((m) => m.sections))}
        <hr />
        <moz-panel-item @click=${this.#switchToClassic}
          >Switch back to the old Developer Hub</moz-panel-item
        >
      </moz-panel-list>
    `;
  }

  render() {
    const profile = this.#profile();
    const menus = profile.data ? [this.#myAddons(), ...MENUS] : MENUS;
    return html`
      <div class="bar">
        <a class="brand" href="${BASE}">
          <moz-icon name="logo-firefox"></moz-icon>
          Add-ons
        </a>
        <nav class="full">
          ${menus.map((menu) => this.#menu(menu))} ${this.#switchBackLink()}
        </nav>
        <nav class="collapsed">${this.#collapsedNav(menus)}</nav>
        <span class="account">
          ${
            profile.isPending
              ? nothing
              : profile.data
                ? html`<devhub-account-menu
                    .profile=${profile.data}
                  ></devhub-account-menu>`
                : this.#loginLink()
          }
        </span>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'devhub-header': DevhubHeader;
  }
}
