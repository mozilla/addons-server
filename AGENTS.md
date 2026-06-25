# addons-server — agent guide

This is the Django backend for addons.mozilla.org (AMO). Everything runs inside Docker.

## Global instructions

- Keep code comments to a strict minimum.
- Do not remove existing comments unless the surrounding code is being refactored.
- If you can't find something quickly, it is better to ask than run local searches.

## Workflow

- Discuss the approach before writing code for non-trivial changes, use plan mode.
- While implementing, run the relevant test suite with `docker compose exec -T web pytest <path to a test file>`.
- Format code with `make format`.

## Before reporting a change as done

**Mandatory** for every code change, no exceptions. Do not send your closing message without completing this. "Tests pass" and "format ran" are not a substitute — they are two of the items, not the whole list.

Walk through the checklist below against the diff you just produced (not unrelated code), and include the result in your closing message. If an item doesn't apply, say so; if something is a tradeoff you accepted, surface it.

- Scope: changes match what was requested — no unrelated edits, refactors, or cleanup that wasn't asked for.
- Correctness: the change actually does what it claims. Edge cases and error paths are handled where they matter.
- Tests: new or changed behavior has test coverage; existing tests still pass. Tests assert behavior, not implementation details.
- Style: follows surrounding code conventions; no stray debug prints, commented-out blocks, or TODOs left behind.
- Comments: only present where the why is non-obvious. Remove anything that just restates the code.
- Dependencies: no new packages added without reason; lockfiles updated if needed.
- Formatting: `make format` has been run.

This checklist is also the standard to apply when explicitly asked to review code (your own or someone else's).
