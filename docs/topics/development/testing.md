# Testing

We're using a mix of [Django's Unit Testing](http://docs.djangoproject.com/en/dev/topics/testing) and [pytest](http://pytest.org/) with [pytest-django](https://pytest-django.readthedocs.io/en/latest/) for our automated testing. This gives us a lot of power and flexibility to test all aspects of the site.

## Configuration

Configuration for your unit tests is handled automatically. The only thing you'll need to ensure is that the database credentials in your settings have full permissions to modify a database with `test_` prepended to it. By default, the database name is `olympia`, so the test database is `test_olympia`. Optionally, in particular if the code you are working on is related to search, you'll want to run Elasticsearch tests. You can use the `test_es` make target for this.

If you don't want to run the Elasticsearch tests, you can use the `test_no_es` target in the Makefile:

```sh
make test_no_es
```

On the contrary, if you only want to run Elasticsearch tests, use the `test_es` target:

```sh
make test_es
```

## Running Tests

To run the whole test suite use:

```sh
pytest
```

There are a lot of options you can pass to adjust the output. Read [pytest](http://pytest.org/) and [pytest-django](https://pytest-django.readthedocs.io/en/latest/) docs for the full set, but some common ones are:

- `-v` to provide more verbose information about the test run
- `-s` tells pytest to not capture the logging output
- `--create-db` tells pytest-django to recreate the database instead of reusing the one from the previous run
- `-x --pdb` to stop on the first failure, and drop into a python debugger
- `--lf` to re-run the last test failed
- `-m test_es` will only run tests that are marked with the `test_es` mark
- `-k foobar` will only run tests that contain `foobar` in their name

There are a few useful makefile targets that you can use:

Run all the tests:

```sh
make test
```

If you need to rebuild the database:

```sh
make test_force_db
```

To fail and stop running tests on the first failure:

```sh
make tdd
```

If you wish to add arguments, or run a specific test, overload the variables (check the Makefile for more information):

```sh
make test ARGS='-v src/olympia/amo/tests/test_url_prefix.py::MiddlewareTest::test_get_app'
```

If you wish to re-run only the tests failed from the previous run:

```sh
make test_failed
```

## Database Setup

Our test runner is configured by default to reuse the database between each test run. If you really want to make a new database (e.g. when models have changed), use the `--create-db` parameter:

```sh
pytest --create-db
```

or

```sh
make test_force_db
```

## Writing Tests

We support two types of automated tests right now and there are some details below but remember, if you're confused look at existing tests for examples.

Also, take some time to get familiar with [pytest](http://pytest.org/) way of dealing with dependency injection, which they call [fixtures](http://pytest.org/en/latest/fixture.html) (which should not be confused with Django's fixtures). They are very powerful, and can make your tests much more independent, cleaner, shorter, and more readable.

### Unit/Functional Tests

Most tests are in this category. Our test classes extend `django.test.TestCase` and follow the standard rules for unit tests. We're using JSON fixtures for the data.

### External calls

Connecting to remote services in tests is not recommended, developers should [mock](http://pypi.python.org/pypi/mock) out those calls instead.

### Fixtures

Some tests rely on zipped `.xip` files to simpulate working with addon artifacts directly.
In order to modify these files you have to unzip/zip the contents ([learn more][extension_workshop-zip])

To unzip the `.xpi` run:

```bash
unzip <path-to-xpi> -d output
```

This will inflate the contents to the ./output directory. Make your modifications and then run:

```bash
cd ./output
zip -r -FS ../<path-to-xpi>
```

To deflate the contents back to the original location. Notice we `cd` into the output directory so
`path-to-xpi` should be relative to the `output` directory.

## Why Tests Fail

Tests usually fail for one of two reasons: The code has changed or the data has changed. A third reason is **time**. Some tests have time-dependent data usually in the fixtures. For example, some featured items have expiration dates.

We can usually save our future-selves time by setting these expirations far in the future.

## Localization Tests

If you want to test that your localization works then you can add in locales in the test directory. For an example see `devhub/tests/locale`. These locales are not in the normal path so should not show up unless you add them to the `LOCALE_PATH`. If you change the .po files for these test locales, you will need to recompile the .mo files manually, for example:

```sh
msgfmt --check-format -o django.mo django.po
```

[extension_workshop-zip]: https://extensionworkshop.com/documentation/publish/package-your-extension/#package-linux
