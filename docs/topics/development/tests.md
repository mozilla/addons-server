# Running Tests

Run tests from outside the docker container with `make`:

```
make test
```

Other, more niche, test commands:

```
make test_failed # rerun the failed tests from the previous run
make test_force_db # run the entire test suite with a new database
make tdd # run the entire test suite, but stop on the first error
```

## Using pytest directly

**For advanced users.**
To run the entire test suite you never need to use _pytest_ directly.

You can connect to the docker container using `make shell`; then use
_pytest_ directly, which allows for finer-grained control of the test
suite.

Run your tests like this:

```
pytest
```

For running subsets of the entire test suite, you can specify which tests
run using different methods:

- _pytest -m es_tests_ to run the tests that are [marked] as _es_tests_
- _pytest -k test_no_license_ to run all the tests that have
  _test_no_license_ in their name
- _pytest src/olympia/addons/tests/test_views.py::TestLicensePage::test_no_license_
  to run this specific test

For more, see the [Pytest usage documentation].

[marked]: http://pytest.org/en/latest/mark.html
[pytest usage documentation]: http://pytest.org/en/latest/usage.html#specifying-tests-selecting-tests
