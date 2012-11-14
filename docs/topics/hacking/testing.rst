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
thing you'll need to ensure is that the database credentials in your
``settings_local.py`` has full permissions to modify a database with ``test-``
prepended to it.  For example, if my database name were ``zamboni`` this
database would be ``test-zamboni``.

Running Tests
-------------

To run the whole shebang use::

    python manage.py test

There are a lot of options you can pass to adjust the output.  Read `the docs`_
for the full set, but some common ones are:

* ``--noinput`` tells Django not to ask about creating or destroying test
  databases.
* ``--loggging-clear-handlers`` tells nose that you don't want to see any
  logging output.  Without this, our debug logging will spew all over your
  console during test runs.  This can be useful for debugging, but it's not that
  great most of the time.  See the docs for more stuff you can do with
  :mod:`nose and logging <nose.plugins.logcapture>`.

Our continuous integration server adds some additional flags for other features
(for example, coverage statistics).  To see what those commands are check out
the build script at :src:`scripts/build.sh`.


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

.. _`javascript-testing`:

JavaScript Tests
----------------

Frontend JavaScript is currently tested with QUnit_, a simple set of
functions for test setup/teardown and assertions.

Running JavaScript Tests
~~~~~~~~~~~~~~~~~~~~~~~~

You can run the tests a few different ways but during development you
probably want to run them in a web browser by opening this page:
http://127.0.0.1:8000/en-US/firefox/qunit/

Before you can load that page, you'll need to adjust your settings_local.py
file so it includes django-qunit:

.. code-block:: python

  INSTALLED_APPS += (
      # ...
      'django_qunit',
  )

Writing JavaScript Tests
~~~~~~~~~~~~~~~~~~~~~~~~

QUnit_ tests for the HTML page above are discovered automatically.  Just add
some_test.js to ``media/js/zamboni/tests/`` and it will run in the suite.  If
you need to include a library file to test against, edit
``media/js/zamboni/tests/suite.json``.

QUnit_ has some good examples for writing tests.  Here are a few
additional tips:

* Any HTML required for your test should go in a sandbox using
  ``tests.createSandbox('#your-template')``.
  See js/zamboni/tests.js for details.
* To make a useful test based on an actual production template, you can create
  a snippet and include that in ``templates/qunit.html`` assigned to its own
  div.  During test setup, reference the div in createSandbox()
* You can use `$.mockjax`_ to test how your code handles server responses,
  errors, and timeouts.

.. _`Django's Unit Testing`: http://docs.djangoproject.com/en/dev/topics/testing
.. _`Selenium repository`: https://github.com/mozilla/Addon-Tests/
.. _`the docs`: http://docs.djangoproject.com/en/dev/topics/testing#id1
.. _Qunit: http://docs.jquery.com/Qunit
.. _`$.mockjax`: http://enterprisejquery.com/2010/07/mock-your-ajax-requests-with-mockjax-for-rapid-development/
.. _mock: http://pypi.python.org/pypi/mock
.. _`nose-blockage`: https://github.com/andymckay/nose-blockage
