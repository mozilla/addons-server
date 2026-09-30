// Public data API for the app. Components attach query controllers and read
// their reactive results; the query layer handles caching, dedup, and the
// mock-vs-API branch.

export {
  addonQuery,
  addonsQuery,
  profileQuery,
  queryKeys,
  updatesQuery,
} from './queries';
export { queryClient } from './query-client';
export * from './types';
