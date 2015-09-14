===================================
Welcome to Olympia's documentation!
===================================

Olympia is the codebase for https://addons.mozilla.org/ ;
the source lives at https://github.com/mozilla/olympia

If you want to build a completely different site with all the same Django
optimizations for security, scalability, L10n, and ease of use, check out
Mozilla's `Playdoh starter kit <http://playdoh.readthedocs.org/>`_.


.. _install-with-docker:

Quickstart
----------

Want the easiest way to start contributing to AMO? Try our docker install in a
few easy steps::

    git clone git://github.com/mozilla/olympia.git
    cd olympia
    pip install docker-compose
    docker-compose build  # Can be very long depending on your internet bandwidth.
    docker-compose run web make initialize_docker  # Answer yes, and create your superuser when asked.
    docker-compose up
    # Once it's all loaded, go to http://localhost:8000 and enjoy!

On the last step, if you're using boot2docker, you-ll need to first find its
ip, and connect to that instead::

    boot2docker ip

This needs a working installation of docker_, please check the information for
your operating system.

.. _docker: https://docs.docker.com/installation/#installation

All the commands should then be run with the `docker-compose run web`
prefix, eg::

    docker-compose run web py.test

.. note:: If you wish to use the Makefile provided with the environment, you
          should first set the `DOCKER_PREFIX` environment variable::

              export DOCKER_PREFIX="docker-compose run --rm web"

          The `make` command will then automatically add the prefix for you!

Any time you update Olympia (e.g., running `git pull`), you should make sure to
update your Docker image and database with any new requirements or migrations::

    docker-compose build  # Installs any new Python requirements in `requirements/*.txt`
    docker-compose run make update_docker  # Runs database migrations, installs npm modules, rebuilds assets.

Please note that any command that would result in files added or modified
outside of the `olympia` folder (eg modifying pip or npm dependencies) won't be
persisted, and so won't survive after the container is finished.
If you need persistence, make sure this command is run in the `Dockerfile` and
do a full rebuild::

    docker-compose build

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

Run your tests like this::

    py.test

There's also a few useful makefile targets like ``test``, ``tdd`` and
``test_force_db``::

    make test

If you want to only run a few tests, you can specify which ones using different
methods:

* `py.test -m es_tests` to run the tests that are marked_ as `es_tests`
* `py.test -k test_no_license` to run all the tests that have
  `test_no_license` in their name
* `py.test apps/addons/tests/test_views.py::TestLicensePage::test_no_license`
  to run only this specific test

You'll find more documentation on this on the `Pytest usage documentation`_.

.. _marked: http://pytest.org/latest/mark.html
.. _Pytest usage documentation:
    http://pytest.org/latest/usage.html#specifying-tests-selecting-tests


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
