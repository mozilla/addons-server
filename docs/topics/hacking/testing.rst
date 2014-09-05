.. _testing:

=======
Testing
=======

We're using a mix of `Django's Unit Testing`_, :mod:`nose <nose>`, and
:mod:`Selenium <selenium>` for our automated testing. This gives us a lot of
power and flexibility to test all aspects of the site.

Selenium tests are maintained in a seperate `Selenium repository`_.

Configuration
-------------

Configuration for your unit tests is mostly handled automatically.  The only
thing you'll need to ensure is that the database credentials in your settings
has full permissions to modify a database with ``test_`` prepended to it. By
default the database name is ``olympia``, so the test database is
``test_olympia``.
Optionally, in particular if the code you are working on is related to search,
you'll want to run Elasticsearch tests. For this, you need to set the setting
``RUN_ES_TESTS=True``. Obviously, you need Elasticsearch to be installed. See
:ref:`elasticsearch` page for details.


Running Tests
-------------

To run the whole shebang use::

    python manage.py test

There are a lot of options you can pass to adjust the output.  Read `the docs`_
for the full set, but some common ones are:

* ``--noinput`` tells Django not to ask about creating or destroying test
  databases.
* ``--logging-clear-handlers`` tells nose that you don't want to see any
  logging output.  Without this, our debug logging will spew all over your
  console during test runs.  This can be useful for debugging, but it's not that
  great most of the time.  See the docs for more stuff you can do with
  :mod:`nose and logging <nose.plugins.logcapture>`.

Our continuous integration server adds some additional flags for other features
(for example, coverage statistics).  To see what those commands are check out
the build script at :src:`scripts/build.sh`.

There are a few useful makefile targets that you can use:

Run all the tests::

    make test

If you need to rebuild the database::

    make test_force_db

To fail and stop running tests on the first failure::

    make tdd

If you wish to add arguments, or run a specific test, overload the variables
(check the Makefile for more information)::

    make ARGS='--verbosity 2 olympia.apps.amo.tests.test_url_prefix:MiddlewareTest.test_get_app' test

Those targets include some useful options, like the ``--with-id`` which allows
you to re-run only the tests failed from the previous run::

    make test_failed


Database Setup
~~~~~~~~~~~~~~

Our test runner will try as hard as it can to skip creating a fresh database
every time.  If you really want to make a new database (e.g. when models have
changed), set the environment variable ``FORCE_DB``. ::

    FORCE_DB=true python manage.py test


Writing Tests
-------------
We support two types of automated tests right now and there are some details
below but remember, if you're confused look at existing tests for examples.


Unit/Functional Tests
~~~~~~~~~~~~~~~~~~~~~
Most tests are in this category.  Our test classes extend
:class:`test_utils.TestCase` and follow the standard rules for unit tests.
We're using JSON fixtures for the data.

External calls
~~~~~~~~~~~~~~
Connecting to remote services in tests is not recommended, developers should
mock_ out those calls instead.

To enforce this we run Jenkins with the `nose-blockage`_ plugin, that
will raise errors if you have an HTTP calls in your tests apart from calls to
the whitelisted domains of `127.0.0.1` and `localhost`.

Why Tests Fail
--------------
Tests usually fail for one of two reasons: The code has changed or the data has
changed.  An third reason is **time**.  Some tests have time-dependent data
usually in the fixtues.  For example, some featured items have expiration dates.

We can usually save our future-selves time by setting these expirations far in
the future.


Localization Tests
------------------
If you want test that your localization works then you can add in locales
in the test directory. For an example see ``devhub/tests/locale``. These locales
are not in the normal path so should not show up unless you add them to the
`LOCALE_PATH`. If you change the .po files for these test locales, you will
need to recompile the .mo files manually, for example::

    msgfmt --check-format -o django.mo django.po


.. _`Django's Unit Testing`: http://docs.djangoproject.com/en/dev/topics/testing
.. _`Selenium repository`: https://github.com/mozilla/Addon-Tests/
.. _`the docs`: http://docs.djangoproject.com/en/dev/topics/testing#id1
.. _mock: http://pypi.python.org/pypi/mock
.. _`nose-blockage`: https://github.com/andymckay/nose-blockage
