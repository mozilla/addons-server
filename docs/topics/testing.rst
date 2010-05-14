.. _testing:

=======
Testing
=======

We're using a mix of `Django's Unit Testing`_, :mod:`nose <nose>`, and
:mod:`Selenium <selenium>` for our automated testing. This gives us a lot of
power and flexibility to test all aspects of the site.


Configuration
-------------

Configuration for your unit tests is mostly handled automatically.  The only
thing you'll need to ensure is that the database credentials in your
``settings_local.py`` has full permissions to modify a database with ``test-``
prepended to it.  For example, if my database name were ``zamboni`` this
database would be ``test-zamboni``.

If you want to run the Selenium tests you'll need a `Selenium RC server`_
running and accepting jobs.  Change the ``SELENIUM_CONFIG`` variable
in ``settings_local.py`` to point to your server and the tests will run
automatically.  If you don't have Selenium set up, the tests will be skipped.


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
* ``-a \!selenium`` tired of running selenium tests?  Add this.

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


Selenium Tests
~~~~~~~~~~~~~~
Selenium tests should go under ``tests/selenium/`` in your apps' directory.
These tests extend :class:`test_utils.SeleniumTestCase` which handles all the
connection steps for you and puts the selenium object in ``self.selenium``.
Full Selenium documentation is available:
http://release.seleniumhq.org/selenium-core/1.0/reference.html


Why Tests Fail
--------------
Tests usually fail for one of two reasons: The code has changed or the data has
changed.  An third reason is **time**.  Some tests have time-dependent data
usually in the fixtues.  For example, some featured items have expiration dates.

We can usually save our future-selves time by setting these expirations far in
the future.


.. _`Django's Unit Testing`: http://docs.djangoproject.com/en/dev/topics/testing
.. _`Selenium RC Server`: http://seleniumhq.org/projects/remote-control/
.. _`the docs`: http://docs.djangoproject.com/en/dev/topics/testing#id1
