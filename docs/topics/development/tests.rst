=============
Running Tests
=============

Run tests from outside the docker container with ``make``::

    make test

Other, more niche, test commands::

    make test_failed # rerun the failed tests from the previous run
    make test_force_db # run the entire test suite with a new database
    make tdd # run the entire test suite, but stop on the first error


Using py.test directly
----------------------

**For advanced users.**
To run the entire test suite you never need to use ``py.test`` directly.

You can connect to the docker container using ``make shell``; then use
``py.test`` directly, which allows for finer-grained control of the test
suite.

Run your tests like this::

    py.test

For running subsets of the entire test suite, you can specify which tests
run using different methods:

* `py.test -m es_tests` to run the tests that are marked_ as `es_tests`
* `py.test -k test_no_license` to run all the tests that have
  `test_no_license` in their name
* `py.test src/olympia/addons/tests/test_views.py::TestLicensePage::test_no_license`
  to run this specific test

For more, see the `Pytest usage documentation`_.

.. _marked: http://pytest.org/latest/mark.html
.. _Pytest usage documentation:
    http://pytest.org/latest/usage.html#specifying-tests-selecting-tests
