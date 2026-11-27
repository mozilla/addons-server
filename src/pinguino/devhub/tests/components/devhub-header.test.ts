import { beforeEach, describe, expect, it, vi } from 'vitest';

// The header's signed-in/out UI keys off the profile query controller. Drive it
// through a mutable state object so each test can pick the auth state without
// touching the network.
const { profileState, addonsState } = vi.hoisted(() => ({
  profileState: {
    data: undefined as
      | {
          id: string;
          name: string;
          pictureUrl?: string;
        }
      | undefined,
    isPending: false,
    isError: false,
  },
  // What the "My Add-ons" menu lists.
  addonsState: {
    data: [] as { slug: string; name: string; kind: string }[],
    isPending: false,
    isError: false,
  },
}));

vi.mock('../../src/data', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../src/data')>();
  return {
    ...actual,
    profileQuery: () => () => profileState,
    navAddonsQuery: () => () => addonsState,
  };
});

import type { DevhubAccountMenu } from '../../src/components/devhub-account-menu';
import type { DevhubHeader } from '../../src/components/devhub-header';
import '../../src/components/devhub-header';
import { mount } from '../helpers/fixture';

function signedOut() {
  Object.assign(profileState, {
    data: undefined,
    isPending: false,
    isError: true,
  });
}

function signedIn({
  name = 'Kate',
  id = '1234',
  pictureUrl = 'https://cdn.test/avatar.png',
}: {
  name?: string;
  id?: string;
  pictureUrl?: string;
} = {}) {
  Object.assign(profileState, {
    data: { id, name, pictureUrl },
    isPending: false,
    isError: false,
  });
}

function loading() {
  Object.assign(profileState, {
    data: undefined,
    isPending: true,
    isError: false,
  });
}

async function header() {
  return await mount<DevhubHeader>('devhub-header');
}

describe('devhub-header', () => {
  beforeEach(() => {
    signedOut();
  });

  it('offers the switch-back link in the full nav', async () => {
    const root = (await header()).shadowRoot as ShadowRoot;
    // The link's rendering and click behaviour live in (and are tested on) the
    // shared switch-back-link component; the header just places it in the nav.
    expect(root.querySelector('nav.full switch-back-link')).not.toBeNull();
  });

  describe('account area', () => {
    it('shows a log-in link and no account menu when signed out', async () => {
      signedOut();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).not.toBeNull();
      expect(root.querySelector('devhub-account-menu')).toBeNull();
    });

    it('links to the login flow with the current path as the return target', async () => {
      signedOut();
      // Stub before mount so the rendered href reflects this location too.
      const loc = {
        pathname: '/en-US/developers/addon/x',
        search: '?a=1',
        href: '',
      };
      vi.stubGlobal('location', loc);

      const root = (await header()).shadowRoot as ShadowRoot;
      const link = root.querySelector('a.login') as HTMLAnchorElement;

      const expected =
        '/api/v5/accounts/login/start/?to=%2Fen-US%2Fdevelopers%2Faddon%2Fx%3Fa%3D1';
      // The href itself carries the return path (no-JS / copy / middle-click).
      expect(link.getAttribute('href')).toBe(expected);

      // Clicking drives a full navigation to the same URL, read live.
      const event = new MouseEvent('click', {
        bubbles: true,
        cancelable: true,
      });
      link.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(true);
      expect(loc.href).toBe(expected);
    });

    it('shows log-in while the profile is loading', async () => {
      loading();
      const root = (await header()).shadowRoot as ShadowRoot;

      expect(root.querySelector('a.login')).not.toBeNull();
      expect(root.querySelector('devhub-account-menu')).toBeNull();
    });

    it('delegates to devhub-account-menu with the profile when signed in', async () => {
      signedIn({ name: 'Kate', id: '1234' });
      const root = (await header()).shadowRoot as ShadowRoot;

      const menu = root.querySelector<DevhubAccountMenu>('devhub-account-menu');
      expect(menu).not.toBeNull();
      expect(menu?.profile).toMatchObject({
        id: '1234',
        name: 'Kate',
        pictureUrl: 'https://cdn.test/avatar.png',
      });
      // The header hands off the signed-in UI entirely; no log-in link.
      expect(root.querySelector('a.login')).toBeNull();
    });
  });
  describe('navigation menus', () => {
    async function menuFor(label: string) {
      const root = (await header()).shadowRoot as ShadowRoot;
      const trigger = [...root.querySelectorAll('moz-button.trigger')].find(
        (el) => el.textContent?.trim() === label,
      );
      const id = trigger?.getAttribute('menu-id') ?? '';
      return { root, trigger, panel: root.getElementById(id) };
    }

    const labels = (panel: Element | null) =>
      [...(panel?.querySelectorAll('moz-panel-item') ?? [])].map((item) =>
        item.textContent?.trim(),
      );

    // A trigger whose menu-id resolves to nothing renders as a dead control.
    it('pairs every trigger with the panel it names', async () => {
      const root = (await header()).shadowRoot as ShadowRoot;
      const triggers = [...root.querySelectorAll('moz-button.trigger')];

      expect(triggers.length).toBeGreaterThan(0);
      for (const trigger of triggers) {
        const id = trigger.getAttribute('menu-id') as string;
        expect(root.getElementById(id)?.tagName.toLowerCase()).toBe(
          'moz-panel-list',
        );
      }
    });

    it('offers only My Add-ons, Documentation & Support and Tools', async () => {
      signedIn();
      const root = (await header()).shadowRoot as ShadowRoot;
      const triggers = [...root.querySelectorAll('moz-button.trigger')].map(
        (el) => el.textContent?.trim(),
      );

      expect(triggers).toEqual([
        'My Add-ons',
        'Documentation & Support',
        'Tools',
      ]);
    });

    it('lists documentation and support, off-site links in a new tab', async () => {
      const { panel } = await menuFor('Documentation & Support');
      const items = [...(panel?.querySelectorAll('moz-panel-item') ?? [])];

      expect(labels(panel)).toEqual([
        'Extension Development',
        'Themes',
        'Developer Add-on Policies',
        'Publishing Guide',
        'Add-on Blog',
        'Add-on Forum',
        'Contact Support',
      ]);
      const offSite = items.filter(
        (i) => i.getAttribute('target') === '_blank',
      );
      expect(offSite).toHaveLength(6);
      for (const item of offSite.slice(0, 4)) {
        expect(item.getAttribute('href')).toMatch(
          /^https:\/\/extensionworkshop\.com\/.*utm_source=addons\.mozilla\.org/,
        );
      }
      expect(
        panel?.querySelector('moz-panel-item[href="/developers/support"]'),
      ).not.toBeNull();
    });

    it('keeps the validator in Tools, in-app', async () => {
      const { panel } = await menuFor('Tools');
      const items = [...(panel?.querySelectorAll('moz-panel-item') ?? [])];

      expect(items.map((i) => i.getAttribute('href'))).toEqual([
        '/developers/addon/validate',
      ]);
      expect(items[0]?.hasAttribute('target')).toBe(false);
    });

    it('hides My Add-ons when signed out', async () => {
      const { trigger } = await menuFor('My Add-ons');
      expect(trigger).toBeUndefined();
    });

    it('lists the developer\u2019s add-ons, typed by kind, above the submit links', async () => {
      signedIn();
      addonsState.data = [
        { slug: 'ad-blocker', name: 'Ad Blocker', kind: 'extension' },
        { slug: 'dark-mode', name: 'Dark Mode', kind: 'theme' },
      ];
      const { panel } = await menuFor('My Add-ons');

      expect(labels(panel)).toEqual([
        'Ad Blocker',
        'Dark Mode',
        'Submit a New Add-on',
        'Submit a New Theme',
      ]);
      const [extension, theme] = [
        ...(panel?.querySelectorAll('moz-panel-item') ?? []),
      ];
      expect(extension.getAttribute('href')).toBe(
        '/developers/addon/ad-blocker',
      );
      expect(extension.getAttribute('icon-start')).toBe('extension');
      expect(theme.getAttribute('icon-start')).toBe('themes');
    });

    it('orders add-ons by name, as the classic devhub does', async () => {
      signedIn();
      addonsState.data = [
        { slug: 'zebra', name: 'Zebra Tabs', kind: 'extension' },
        { slug: 'ad-blocker', name: 'Ad Blocker', kind: 'extension' },
        { slug: 'dark-mode', name: 'Dark Mode', kind: 'theme' },
      ];
      const { panel } = await menuFor('My Add-ons');

      expect((labels(panel) as string[]).slice(0, 3)).toEqual([
        'Ad Blocker',
        'Dark Mode',
        'Zebra Tabs',
      ]);
    });

    it('caps the list and points the overflow at the dashboard', async () => {
      signedIn();
      addonsState.data = Array.from({ length: 9 }, (_, i) => ({
        slug: `addon-${i}`,
        name: `Add-on ${i}`,
        kind: 'extension',
      }));
      const { panel } = await menuFor('My Add-ons');

      const names = labels(panel) as string[];
      expect(names.filter((n) => n.startsWith('Add-on '))).toHaveLength(7);
      expect(names).toContain('More add-ons\u2026');
      expect(
        panel?.querySelector('moz-panel-item[href="/developers/"]'),
      ).not.toBeNull();
    });
  });
  describe('hover menus', () => {
    // moz-panel-list isn't upgraded here, so give each panel the two methods
    // the header calls.
    async function hoverable() {
      const root = (await header()).shadowRoot as ShadowRoot;
      for (const panel of root.querySelectorAll('moz-panel-list')) {
        Object.assign(panel, {
          open: false,
          show: vi.fn(function (this: { open: boolean }) {
            this.open = true;
          }),
          hide: vi.fn(function (this: { open: boolean }) {
            this.open = false;
          }),
        });
      }
      const trigger = (label: string) =>
        [...root.querySelectorAll<HTMLElement>('moz-button.trigger')].find(
          (el) => el.textContent?.trim() === label,
        ) as HTMLElement;
      const panel = (id: string) =>
        root.getElementById(id) as HTMLElement & {
          show: ReturnType<typeof vi.fn>;
          hide: ReturnType<typeof vi.fn>;
        };
      return { trigger, panel };
    }

    const pointer = (type: string, pointerType = 'mouse') =>
      new PointerEvent(type, { pointerType });

    it('opens a menu on mouse hover, anchored to its trigger', async () => {
      const { trigger, panel } = await hoverable();
      const tools = trigger('Tools');
      const enter = pointer('pointerenter');

      tools.dispatchEvent(enter);

      expect(panel('nav-tools').show).toHaveBeenCalledWith(enter, tools);
    });

    it('leaves touch to the click toggle', async () => {
      const { trigger, panel } = await hoverable();

      trigger('Tools').dispatchEvent(pointer('pointerenter', 'touch'));

      expect(panel('nav-tools').show).not.toHaveBeenCalled();
    });

    it('closes once the pointer leaves, unless it reaches the menu', async () => {
      vi.useFakeTimers();
      try {
        const { trigger, panel } = await hoverable();
        const tools = trigger('Tools');

        tools.dispatchEvent(pointer('pointerenter'));
        tools.dispatchEvent(pointer('pointerleave'));
        panel('nav-tools').dispatchEvent(pointer('pointerenter'));
        vi.runAllTimers();
        expect(panel('nav-tools').hide).not.toHaveBeenCalled();

        panel('nav-tools').dispatchEvent(pointer('pointerleave'));
        vi.runAllTimers();
        expect(panel('nav-tools').hide).toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it('shows one hovered menu at a time', async () => {
      const { trigger, panel } = await hoverable();

      trigger('Tools').dispatchEvent(pointer('pointerenter'));
      trigger('Documentation & Support').dispatchEvent(pointer('pointerenter'));

      expect(panel('nav-tools').hide).toHaveBeenCalled();
      expect(panel('nav-documentation').show).toHaveBeenCalled();
    });
  });

  describe('drawer', () => {
    async function drawer() {
      const el = await header();
      const root = el.shadowRoot as ShadowRoot;
      const dialog = () => root.querySelector('moz-dialog.drawer');
      const sections = () => [
        ...root.querySelectorAll('moz-dialog moz-details'),
      ];
      const open = async () => {
        root
          .querySelector<HTMLElement>('moz-button.drawer-button')
          ?.dispatchEvent(new MouseEvent('click'));
        await el.updateComplete;
      };
      return { el, root, dialog, sections, open };
    }

    it('opens from a labelled menu button', async () => {
      const { root, dialog, open } = await drawer();
      const button = root.querySelector('moz-button.drawer-button');

      expect(button?.getAttribute('icon-only')).toBe('Menu');
      expect(dialog()?.hasAttribute('open')).toBe(false);
      await open();
      expect(dialog()?.hasAttribute('open')).toBe(true);
      expect(dialog()?.hasAttribute('dismissable')).toBe(true);
    });

    it('has a closed section for each menu the full nav shows', async () => {
      signedIn();
      addonsState.data = [
        { slug: 'ad-blocker', name: 'Ad Blocker', kind: 'extension' },
      ];
      const { sections } = await drawer();

      expect(sections().map((d) => d.getAttribute('heading'))).toEqual([
        'My Add-ons',
        'Documentation & Support',
        'Tools',
      ]);
      expect(sections().some((d) => d.hasAttribute('open'))).toBe(false);
    });

    it('drops My Add-ons when signed out, like the full nav', async () => {
      const { sections } = await drawer();

      expect(sections().map((d) => d.getAttribute('heading'))).toEqual([
        'Documentation & Support',
        'Tools',
      ]);
    });

    it('keeps one section open at a time', async () => {
      const { el, sections } = await drawer();
      const toggle = async (i: number, open: boolean) => {
        sections()[i].dispatchEvent(
          new CustomEvent('moz-details:toggle', { detail: { open } }),
        );
        await el.updateComplete;
      };
      const opened = () =>
        sections()
          .filter((d) => d.hasAttribute('open'))
          .map((d) => d.getAttribute('heading'));

      await toggle(0, true);
      expect(opened()).toEqual(['Documentation & Support']);
      await toggle(1, true);
      expect(opened()).toEqual(['Tools']);
      await toggle(1, false);
      expect(opened()).toEqual([]);
    });

    it('captions a menu’s later sections and keeps links’ targets', async () => {
      signedIn();
      addonsState.data = [];
      const { sections } = await drawer();
      const [myAddons, docs] = sections();

      expect(
        [...myAddons.querySelectorAll('h3')].map((h) => h.textContent?.trim()),
      ).toEqual(['Create New Add-on']);
      const blog = [...docs.querySelectorAll('a')].find(
        (a) => a.textContent?.trim() === 'Add-on Blog',
      );
      expect(blog?.getAttribute('target')).toBe('_blank');
      const support = docs.querySelector('a[href="/developers/support"]');
      expect(support?.hasAttribute('target')).toBe(false);
    });

    it('closes when a link is followed or it is dismissed', async () => {
      const { el, dialog, sections, open } = await drawer();

      await open();
      sections()[0]
        .querySelector('a')
        ?.addEventListener('click', (e) => e.preventDefault());
      sections()[0].querySelector('a')?.click();
      await el.updateComplete;
      expect(dialog()?.hasAttribute('open')).toBe(false);

      await open();
      dialog()?.dispatchEvent(new CustomEvent('moz-dialog:dismiss'));
      await el.updateComplete;
      expect(dialog()?.hasAttribute('open')).toBe(false);
    });

    it('keeps the switch back link reachable', async () => {
      const { dialog } = await drawer();

      expect(
        dialog()?.querySelector('switch-back-link')?.textContent?.trim(),
      ).toBe('Switch back to the old Developer Hub');
    });
  });
});
