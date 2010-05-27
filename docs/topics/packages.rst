.. _packages:

====================
Packaging in Zamboni
====================

There are two ways of getting packages for zamboni.  The first is to install
everything using pip.  We have our packages separated into three files:

:src:`requirements/compiled.txt`
    All packages that require (or go faster with) compilation.  These can't be
    distributed cross-platform, so they need to be installed through your
    system's package manager or pip.

:src:`requirements/prod.txt`
    The minimal set of packages you need to run zamboni in production.  You
    also need to get ``requirements/compiled.txt``.

:src:`requirements/dev.txt`
    All the packages needed for running tests and development servers.  This
    automatically includes ``requirements/prod.txt``.


Installing through pip
----------------------

You can get a development environment with ::

    pip install -r requirements/dev.txt -r requirements/compiled.txt


Using the vendor library
------------------------

The other method is to use the /vendor library of all packages and
repositories.  These are maintained by Hudson in the zamboni-lib repository.

Check out the vendor lib with ::

    git clone --recursive git://github.com/jbalogh/zamboni-lib.git ./vendor

Once the zamboni-lib repo has been downloaded to ``/vendor``, you only need to
install the compiled packages.  These can come from your system package manager
or from ::

    pip install -r requirements/compiled.txt


Adding new packages
-------------------

The vendor repo was seeded with ::

    pip install --no-install --build=vendor/packages --src=vendor/src -I -r requirements/dev.txt

Then I added everything in ``/packages`` and set up submodules in ``/src`` (see
below).  We'll be keeping this up to date through Hudson, but if you add new
packages you should seed them yourself.

If we wanted to add a new dependency called ``cheeseballs`` to zamboni, you
would add it to ``requirements/prod.txt`` or ``requirements/dev.txt`` and then
do ::

    pip install --no-install --build=vendor/packages --src=vendor/src -I cheeseballs

Then you need to update ``vendor/zamboni.pth``.  Python uses ``.pth`` files to
dynamically add directories to ``sys.path``
(`docs <http://docs.python.org/library/site.html>`_).

I created ``zamboni.pth`` with this::

    find packages src -type d -depth 1 > zamboni.pth

``html5lib`` and ``selenium`` are troublesome, so they need to be sourced with
``packages/html5lib/src`` and ``packages/selenium/src``.  Hopefully you won't
hit any snags like that.


Adding submodules
~~~~~~~~~~~~~~~~~
::

    for f in src/*
        pushd $f >/dev/null && REPO=$(git config remote.origin.url) && popd > /dev/null && git submodule add $REPO $f

Holy readability batman!
