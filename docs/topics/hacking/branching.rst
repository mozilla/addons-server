.. _branching:

================
Push From Master
================

We deploy from the `master`_ branch once a month. If you commit something to master
that needs additional QA time, be sure to use a `waffle`_ feature flag.


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

Here are some tips on `Using topic branches and interactive rebasing effectively <http://blog.mozilla.com/webdev/2011/11/21/git-using-topic-branches-and-interactive-rebasing-effectively/>`_.

.. _master: http://github.com/mozilla/olympia/tree/master
.. _waffle: https://github.com/jsocol/django-waffle
