.. _packages:

====================
Packaging in Olympia
====================

There are two ways of getting packages for olympia. The first is to install
everything using pip. We have our packages separated into three files:

:src:`requirements/compiled.txt`
    All packages that require (or go faster with) compilation. These can't be
    distributed cross-platform, so they need to be installed through your
    system's package manager or pip.

:src:`requirements/prod.txt`
    The minimal set of packages you need to run olympia in production. You
    also need to get ``requirements/compiled.txt``.

:src:`requirements/dev.txt`
    All the packages needed for running tests and development servers. This
    automatically includes ``requirements/prod.txt``.


Installing through pip
----------------------

You can get a development environment with ::

    pip install --no-deps -r requirements/dev.txt
