===================================
Welcome to Olympia's documentation!
===================================

Olympia is the codebase for https://addons.mozilla.org/ ;
the source lives at https://github.com/mozilla/olympia

If you want to build a completely different site with all the same Django
optimizations for security, scalability, L10n, and ease of use, check out
Mozilla's `Playdoh starter kit <http://playdoh.readthedocs.org/>`_.


Quickstart
----------

Want the easiest way to start contributing to AMO? Try our docker install in a
few easy steps::

    git clone git://github.com/mozilla/olympia.git
    cd olympia
    pip install fig
    fig build  # Can be very long depending on your internet bandwidth.
    fig run web make initialize_db  # Create your superuser when asked.
    fig up
    # Once it's all loaded, go to http://localhost:8000 and enjoy!

This needs a working installation of docker_, please check the information for
your operating system.

.. _docker: https://docs.docker.com/installation/#installation

All the commands should then be run with the `fig run --rm web` prefix, eg::

    fig run --rm web manage.py test

.. note:: If you wish to use the Makefile provided with the environment, you
          should first set the `FIG_PREFIX` environment variable::

              export FIG_PREFIX="fig run --rm web"

          The `make` command will then automatically add the prefix for you!

.. note:: The `--rm` parameter to the `fig run` command will tell fig to remove
          the created container straight after being finished with it, to avoid
          useless containers packing up after each command.

Please note that any command that would result in files added or modified
outside of the `olympia` folder (eg modifying pip or npm dependencies) won't be
persisted, and so won't survive after the container is finished.
If you need persistence, make sure this command is run in the `Dockerfile` and
do a full rebuild::

    fig build

Installation
------------
If you need more, or would rather install manually, follow the :ref:`manual
Olymia installation <installation>` instructions.


Contents
--------

.. toctree::
   :maxdepth: 3

   topics/install-olympia/index
   topics/hacking/index

.. toctree::
   :maxdepth: 2
   :glob:

   topics/*

gettext in Javascript
~~~~~~~~~~~~~~~~~~~~~

We have gettext in javascript!  Just mark your strings with ``gettext()`` or
``ngettext()``.  There isn't an ``_`` alias right now, since underscore.js has
that.  If we end up with a lot of js translations, we can fix that.  Check it
out::

    cd locale
    ./extract-po.py -d javascript
    pybabel init -l en_US -d . -i javascript.pot -D javascript
    perl -pi -e 's/fuzzy//' en_US/LC_MESSAGES/javascript.po
    pybabel compile -d . -D javascript
    open http://0:8000/en-US/jsi18n/

Git Bisect
~~~~~~~~~~

Did you break something recently?  Are you wondering which commit started the
problem? ::

    git bisect start
    git bisect bad
    git bisect good <master>  # Put the known-good commit here.
    git bisect run fab test
    git bisect reset

Git will churn for a while, running tests, and will eventually tell you where
you suck.  See the git-bisect man page for more details.


Running Tests
~~~~~~~~~~~~~

* Run your tests like this::

      python manage.py test --noinput --logging-clear-handlers

  * ``--noinput`` tells Django not to ask about creating or destroying test
    databases.
  * ``--logging-clear-handlers`` tells nose that you don't want to see any
    logging output.  Without this, our debug logging will spew all over your
    console during test runs.  This can be useful for debugging, but it's not that
    great most of the time.  See the docs for more stuff you can do with
    :mod:`nose and logging <nose.plugins.logcapture>`.

There's also a few useful makefile targets like ``test``, ``tdd`` and
``test_force_db``::

    make test


Building Docs
~~~~~~~~~~~~~

To simply build the docs::

    make docs

If you're working on the docs, use ``make loop`` to keep your built pages
up-to-date::

    cd docs
    make loop


Indices and tables
~~~~~~~~~~~~~~~~~~

* :ref:`genindex`
* :ref:`modindex`
