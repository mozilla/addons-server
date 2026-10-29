// AMO serializes `addon.status` and `version.file.status` through one map
// (amo.STATUS_CHOICES_API), so the strings share a namespace although each
// field only uses the subset documented in docs/topics/api/addons.rst.

// Mirrors acorn's StatusBadgeType, kept local so data/ needn't depend on the
// component library.
type BadgeType = 'default' | 'ghost' | 'success' | 'warning' | 'critical';

export interface StatusInfo {
  label: string;
  badge: BadgeType;
}

export type ApiStatus =
  | 'incomplete'
  | 'unreviewed'
  | 'nominated'
  | 'public'
  | 'disabled'
  | 'deleted'
  | 'rejected';

// `unreviewed` is the file-only spelling of `nominated`.
export type AddonStatus = Exclude<ApiStatus, 'unreviewed'>;
export type VersionStatus = Extract<
  ApiStatus,
  'unreviewed' | 'public' | 'disabled'
>;

export const ADDON_STATUS: Record<AddonStatus, StatusInfo> = {
  public: { label: 'Approved', badge: 'success' },
  nominated: { label: 'Awaiting review', badge: 'warning' },
  incomplete: { label: 'Incomplete', badge: 'warning' },
  rejected: { label: 'Listing content rejected', badge: 'critical' },
  disabled: { label: 'Disabled by Mozilla', badge: 'critical' },
  deleted: { label: 'Deleted', badge: 'critical' },
};

export const VERSION_STATUS: Record<VersionStatus, StatusInfo> = {
  public: { label: 'Approved', badge: 'success' },
  unreviewed: { label: 'Awaiting review', badge: 'warning' },
  // Collapses rejected, Mozilla-disabled and author-disabled.
  disabled: { label: 'Disabled', badge: 'critical' },
};

const UNKNOWN: StatusInfo = { label: 'Unknown', badge: 'default' };

// Review state only; author-hiding reports through VISIBILITY.
export function resolveAddonStatus(status: string | undefined): StatusInfo {
  return ADDON_STATUS[status as AddonStatus] ?? UNKNOWN;
}

// `reviewed` tells a rejection from a file no human reached; both are `disabled`.
export function resolveVersionStatus(
  status: string | undefined,
  {
    isDisabled = false,
    reviewed,
  }: { isDisabled?: boolean; reviewed?: string | null } = {},
): StatusInfo {
  const info = VERSION_STATUS[status as VersionStatus];
  if (!info) return UNKNOWN;
  if (status !== 'disabled') return info;
  if (isDisabled) return { label: 'Disabled by you', badge: 'warning' };
  return reviewed
    ? { label: 'Rejected', badge: 'critical' }
    : VERSION_STATUS.unreviewed;
}

export type AddonVisibility = 'visible' | 'invisible';

export const VISIBILITY: Record<AddonVisibility, StatusInfo> = {
  visible: { label: 'Visible', badge: 'success' },
  invisible: { label: 'Invisible', badge: 'ghost' },
};

// `is_disabled` writes to the author's own setting but reads back true for
// Mozilla-disabled add-ons too, so this can't tell the two apart.
export function resolveVisibility(isDisabled: boolean): AddonVisibility {
  return isDisabled ? 'invisible' : 'visible';
}

// The single state to show for a listing. Author-set invisibility outranks the
// review status: it's the thing they chose, and the thing they undo.
export function resolveListingState(
  status: StatusInfo,
  visibility: AddonVisibility,
): StatusInfo {
  return visibility === 'invisible' ? VISIBILITY.invisible : status;
}

// An author can't un-hide what Mozilla disabled or deleted.
// (devhub/includes/listing_visibility.html)
export function canChangeVisibility(status: string | undefined): boolean {
  return status !== 'disabled' && status !== 'deleted';
}
