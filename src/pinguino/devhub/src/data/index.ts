// Public data API for the app. Components attach query controllers and read
// their reactive results; the query layer handles caching, and dedup.

export { fetchEulaPolicy } from './api';
export { isAddonOwner } from './permissions';
export {
  acceptAgreement,
  addonOwnershipQuery,
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
  removeAddon,
  removeAuthor,
  removePreview,
  setAddonVisibility,
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
  resolveListingState,
  resolveVersionStatus,
  resolveVisibility,
  type StatusInfo,
  VERSION_STATUS,
  type VersionStatus,
  VISIBILITY,
} from './statuses';
export * from './types';
