=============
Running Tests
=============

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
* `py.test src/olympia/addons/tests/test_views.py::TestLicensePage::test_no_license`
  to run only this specific test

You'll find more documentation on this on the `Pytest usage documentation`_.

.. _marked: http://pytest.org/latest/mark.html
.. _Pytest usage documentation:
    http://pytest.org/latest/usage.html#specifying-tests-selecting-tests
