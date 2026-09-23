// AMO API endpoints for the DevHub. Each function fetches over ./http and maps
// the v5 response onto our domain types. Caching, dedup, and lifetime live in
// the query layer (./queries), not here.

import { apiFetch, author } from './http';
import type { Addon, AddonKind, Developer, Update } from './types';

// The subset of an AMO v5 addon search result we read.
interface ApiAddon {
  slug: string;
  name: string | Record<string, string>;
  type: string;
  status?: string;
  is_disabled?: boolean;
  last_updated?: string;
  current_version?: { id?: number; version?: string };
}

// The subset of an AMO v5 reviewnotes (ActivityLog) entry we read.
interface ApiActivity {
  id: number;
  action?: string;
  action_label?: string;
  comments?: string;
  date?: string;
}

// The current account, from /accounts/profile/. `name` already falls back to a
// generated name server-side; display_name is the user-chosen label when set.
interface ApiProfile {
  display_name?: string;
  name?: string;
  username?: string;
}

function localized(value: string | Record<string, string> | undefined): string {
  if (!value) return '';
  if (typeof value === 'string') return value;
  return value['en-US'] ?? Object.values(value)[0] ?? '';
}

function formatDate(iso: string | undefined): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const month = date.toLocaleString('en-US', { month: 'short' });
  return `${month} ${date.getUTCDate()} ${date.getUTCFullYear()}`;
}

function mapAddon(a: ApiAddon): Addon {
  const kind: AddonKind = a.type === 'statictheme' ? 'theme' : 'extension';
  const live = a.status === 'public' && !a.is_disabled;
  return {
    slug: a.slug,
    name: localized(a.name),
    kind,
    icon: kind === 'theme' ? 'themes' : 'extension',
    statusLabel: live
      ? kind === 'theme'
        ? 'Live theme'
        : 'Live add-on'
      : (a.status ?? 'Unknown'),
    version: a.current_version?.version ?? '—',
    versionId: a.current_version?.id,
    lastUpdated: formatDate(a.last_updated),
    visibility: live ? 'live' : 'hidden',
    // Distribution isn't exposed by the search API yet; default until it is.
    distribution: 'amo',
  };
}

function mapActivity(a: ApiActivity, addon: Addon): Update {
  const label = a.action_label ?? a.action ?? 'Update';
  // Best-effort: the RSS/activity log has no explicit approved flag, so infer it
  // from the action name (see the backend TODO on fetchUpdates).
  const approved = /approv|public/i.test(a.action ?? label);
  return {
    id: `${addon.slug}-${a.id}`,
    approved,
    title: `Your version is ${approved ? 'approved' : 'flagged'}.`,
    message: a.comments || label,
    version: addon.version,
    versionStatus: label,
    tags: [],
    date: formatDate(a.date),
  };
}

export async function fetchProfile(): Promise<Developer> {
  const data = await apiFetch<ApiProfile>('/accounts/profile/');
  return { name: data.display_name || data.name || data.username || '' };
}

export async function fetchAddons(): Promise<Addon[]> {
  const path = `/addons/search/?author=${encodeURIComponent(author)}&lang=en-US&page_size=50`;
  const data = await apiFetch<{ results?: ApiAddon[] }>(path);
  return (data.results ?? []).map(mapAddon);
}

// TODO(backend): this builds the updates feed by fetching each add-on's current
// version's review notes (one request per add-on) and inferring approved/flagged
// from the action label. It should be replaced by a single JSON developer-activity
// endpoint — the same ActivityLog query behind /developers/feed, serialized like
// reviewnotes — giving one request, real structure (status/date/version), and CORS.
export async function fetchUpdates(addons: Addon[]): Promise<Update[]> {
  const withVersions = addons.filter((a) => a.versionId != null);
  const perAddon = await Promise.all(
    withVersions.map(async (addon) => {
      const path = `/addons/addon/${encodeURIComponent(addon.slug)}/versions/${addon.versionId}/reviewnotes/`;
      const data = await apiFetch<{ results?: ApiActivity[] }>(path);
      return (data.results ?? []).map((a) => ({ activity: a, addon }));
    }),
  );
  return (
    perAddon
      .flat()
      // ISO 8601 dates sort lexicographically, so newest-first by the raw date.
      .sort((x, y) =>
        (y.activity.date ?? '').localeCompare(x.activity.date ?? ''),
      )
      .map(({ activity, addon }) => mapActivity(activity, addon))
  );
}
