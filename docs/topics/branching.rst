.. _branching:

===================
How We Do Branching
===================

We manage our branches in a similar manner to `nvie's branching model`_.  The
main difference is that we develop all code on the `master`_ branch and use the
`next`_ branch as the place for staging releases.

New development happens on ``master``, and is visible on
https://preview.addons.mozilla.org.  When we have a code freeze (every one or
two weeks), the ``next`` branch is synced with master and is visible on
https://next.addons.mozilla.org.

Tags should be created off of the ``next`` branch.  If we need to release a
hotfix, it should be applied to the ``next`` branch and tagged from there.


Local Branches
--------------

Most new code is developed in local one-off branches, usually encompassing one
or two patches to fix a bug.  Upstream doesn't care how you do local
development, but we don't want to see a merge commit every time you merge a
single patch from a branch.  Merge commits make for a noisy history, which is
not fun to look at and can make it difficult to cherry-pick hotfixes to a
release branch.  We do like to see merge commits when you're committing a set
of related patches from a feature branch.  The rule of thumb is to rebase and
use fast-forward merge for single patches or a branch of unrelated bug fixes,
but to use a merge commit if you have multiple commits that form a cohesive unit.


.. _nvie's branching model: http://nvie.com/posts/a-successful-git-branching-model/
.. _master: http://github.com/jbalogh/zamboni/tree/master
.. _next: http://github.com/jbalogh/zamboni/tree/next
