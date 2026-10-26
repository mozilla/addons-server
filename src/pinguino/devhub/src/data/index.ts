// Public data API for the app. Components attach query controllers and read
// their reactive results; the query layer handles caching, and dedup.

export { ACTIVITY_PAGE_SIZE, fetchEulaPolicy } from './api';
export {
  acceptAgreement,
  activityQuery,
  addonQuery,
  addonsQuery,
  agreementQuery,
  authorsQuery,
  categoriesQuery,
  createAuthor,
  createPreview,
  createUpload,
  createVersion,
  disableVersion,
  eulaPolicyQuery,
  pendingAuthorsQuery,
  profileQuery,
  queryKeys,
  removeAuthor,
  removePreview,
  updateAddon,
  updateAuthor,
  updateEulaPolicy,
  updateIcon,
  updatePreview,
  updatesQuery,
  uploadQuery,
  uploadVersionNotes,
  uploadVersionSource,
  versionQuery,
} from './queries';
export { queryClient } from './query-client';
export {
  ADDON_STATUS,
  type AddonStatus,
  type AddonVisibility,
  type ApiStatus,
  canChangeVisibility,
  resolveAddonStatus,
  resolveVersionStatus,
  resolveVisibility,
  type StatusInfo,
  VERSION_STATUS,
  type VersionStatus,
  VISIBILITY,
} from './statuses';
export * from './types';
