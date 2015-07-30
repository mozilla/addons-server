.. _packages:

====================
Packaging in Olympia
====================

We have our packages separated into three files:

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

You can get a development environment with::

    pip install --no-deps --exists-action=w -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/wheelhouse --find-links https://pyrepo.addons.mozilla.org/ --no-index

Or more simply with::

    make update_deps

The latter will also install the npm dependencies.


Using peep instead of pip
-------------------------

To have reproducible environments and make sure what we install is what we
wanted to install, we're moving to use peep_ instead of pip::

    python peep.py install --exists-action=w -r requirements/dev.txt --find-links https://pyrepo.addons.mozilla.org/wheelhouse --find-links https://pyrepo.addons.mozilla.org/ --no-index

This will however need all the proper hashes in the requirements files for each
of the dependencies. They are already present for linux, but if you're using
another platform, some of those dependencies will use different files (eg if
they contain binaries), and will thus need another hash.

.. _peep: https://github.com/erikrose/peep
