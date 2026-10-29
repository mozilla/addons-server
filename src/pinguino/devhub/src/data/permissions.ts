// What the signed-in developer is allowed to do with an add-on. The API is the
// real authority; these mirror its rules so the UI doesn't offer actions it
// would refuse.

import type { AddonAuthor } from './types';

/**
 * Owners can delete the add-on and manage its authors; developers can't.
 *
 * Either argument may still be loading, and an unknown answer is "no" — better
 * to withhold an action for a moment than to offer one that 403s.
 */
export function isAddonOwner(
  authors: AddonAuthor[] | undefined,
  userId: number | undefined,
): boolean {
  if (userId === undefined) return false;
  return (authors ?? []).some(
    (author) => author.userId === userId && author.role === 'owner',
  );
}
