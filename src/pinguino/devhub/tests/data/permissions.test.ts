import { describe, expect, it } from 'vitest';
import { isAddonOwner } from '../../src/data/permissions';

const authors = [
  { userId: 7, name: 'Kate', role: 'owner' as const },
  { userId: 8, name: 'Sam', role: 'developer' as const },
];

describe('isAddonOwner', () => {
  it('recognises the owner among the authors', () => {
    expect(isAddonOwner(authors, 7)).toBe(true);
  });

  it('rejects a developer, and anyone not on the add-on', () => {
    expect(isAddonOwner(authors, 8)).toBe(false);
    expect(isAddonOwner(authors, 99)).toBe(false);
  });

  // Either side may still be loading; withhold the action until both are in.
  it('answers no while the authors or the user are unknown', () => {
    expect(isAddonOwner(undefined, 7)).toBe(false);
    expect(isAddonOwner(authors, undefined)).toBe(false);
    expect(isAddonOwner([], 7)).toBe(false);
  });
});
