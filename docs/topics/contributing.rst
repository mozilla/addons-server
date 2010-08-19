.. _contributing:

============
Contributing
============

The easiest way to let us know about your awesome work is to send a pull
request on github or in IRC.  Point us to a branch with your new code and we'll
go from there.  You can attach a patch to a bug if you're more comfortable that
way.


The Perfect Git Configuration
-----------------------------

We're going to talk about two git repositories:

* *origin* will be the main zamboni repo at http://github.com/jbalogh/zamboni.
* *mine* will be your fork at http://github.com/:user/zamboni.

There should be something like this in your ``.git/config`` already::

    [remote "origin"]
        url = git://github.com/jbalogh/zamboni.git
        fetch = +refs/heads/*:refs/remotes/origin/*

Now we'll set up your master to pull directly from the upstream zamboni::

    [branch "master"]
        remote = origin
        merge = master
        rebase = true

This can also be done through the ``git config`` command (e.g.
``git config branch.master.remote origin``) but editing ``.git/config`` is
often easier.

After you've forked the repository on github, tell git about your new repo::

    git remote add -f mine git@github.com:user/zamboni.git

Make sure to replace *user* with your name.


Working on a Branch
~~~~~~~~~~~~~~~~~~~

Let's work on a bug in a branch called *my-bug*::

    git checkout -b my-bug master

Now we're switched to a new branch that was copied from master.  We like to
work on feature branches, but the master is still moving along.  How do we keep
up? ::

    git fetch origin && git rebase origin/master

If you want to keep the master branch up to date, do it this way::

    git checkout master && git pull && git checkout @{-1} && git rebase master

That updated master and then switched back to update our branch.


Publishing your Branch
~~~~~~~~~~~~~~~~~~~~~~
The syntax is ``git push <repository> <branch>``.  Here's how to push the
``my-bug`` branch to your clone::

    git push mine my-bug
