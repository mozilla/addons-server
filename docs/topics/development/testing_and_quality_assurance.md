# Testing and Quality Assurance

The **addons-server** project employs a comprehensive testing framework to ensure code quality and stability. This section covers the tools and practices used for testing and quality assurance.

## Code Quality and Linting

The project uses `ruff` and `prettier` to format and lint code for Python and Node.js, respectively. Ensuring your branch has properly formatted code can be done easily:

- **Ruff**: Used for linting and formatting Python code.
- **Curlylint**: Used for linting and formatting django/jinja templates.
- **ESLint**: Used for linting and formatting Node.js code.
- **Prettier**: Used for linting and formatting Node.js code.

To format and lint your code, run:

```sh
make format
```

This command ensures that your code adheres to the project's style guidelines.

## Build Verification

Build verification is a crucial step in our CI pipeline. We run all CI checks using an actual Docker build that is nearly identical to our local build. This ensures a high level of confidence between what you develop locally and what is tested in CI.

We verify the build itself by running checks against both our Docker configurations and our Docker container. To verify your container locally, run:

```sh
make check
```

This command runs a series of checks to ensure the Docker setup and container are functioning correctly.

## Testing

The project primarily uses Python for tests, with some Node.js tests as well. Here's how to handle testing:

- **Python Tests**: The majority of the tests are written in Python.
- **Node.js Tests**: There are some tests written in Node.js.

To run specialized tests, you can shell into the container or check `Makefile-docker` for specific test commands.

### Running Tests

To run the whole test suite, use:

```sh
make test
```

- **Running Specialized Tests**: Shell into the container and run the desired test command.

```sh
make shell
make test_some_specific_test
```

To speed up test execution, you can parallelize and/or share tests. The project uses `pytest-split` and `pytest-xdist` to facilitate this. These tools allow for distributed and parallel test execution, significantly reducing test times.

- **Parallel Testing**:

```sh
pytest -n auto  # pytest-xdist
```

#### Configuration

Configuration for your unit tests is handled automatically. Ensure that the database credentials in your settings have full permissions to modify a database with `test_` prepended to it. By default, the database name is `olympia`, so the test database is `test_olympia`.

If the code you are working on is related to search, you'll want to run Elasticsearch tests. Ensure Elasticsearch is installed. See the :ref:`elasticsearch` page for details.

- To exclude Elasticsearch tests:

```sh
make test_no_es
```

- To run only Elasticsearch tests:

```sh
make test_es
```

### Using `pytest` Directly

For advanced users, you can connect to the Docker container using `make shell` and then use `pytest` directly, which allows for finer-grained control of the test suite.

```sh
pytest
```

Examples of running subsets of the test suite:

- `pytest -m es_tests` to run tests marked as `es_tests`.
- `pytest -k test_no_license` to run tests with `test_no_license` in their name.
- `pytest src/olympia/addons/tests/test_views.py` to run all tests in a given file.
- `pytest src/olympia/addons/tests/test_views.py::TestLicensePage` to run a specific test suite.
- `pytest src/olympia/addons/tests/test_views.py::TestLicensePage::test_no_license` to run a specific test.

For more details, see the [Pytest usage documentation](http://pytest.org/en/latest/usage.html#specifying-tests-selecting-tests).

### Useful Makefile Targets

- Run all tests:

```sh
make test
```

- Rebuild the database and run tests:

```sh
make test_force_db
```

- Stop on the first test failure:

```sh
make tdd
```

- Run tests with specific arguments or specific tests:

```sh
make test ARGS='-v src/olympia/amo/tests/test_url_prefix.py::MiddlewareTest::test_get_app'
```

- Re-run only the tests that failed in the previous run:

```sh
make test_failed
```

### Writing Tests

We support two types of automated tests:

- **Unit/Functional Tests**: Most tests fall into this category. Test classes extend `django.test.TestCase` and follow standard unit testing rules, using JSON fixtures for data.
- **External Calls**: Avoid connecting to remote services in tests. Instead, mock out those calls with [responses](https://pypi.org/project/responses/).

### Localization Tests

If you want to test localization, add locales in the test directory (e.g., `devhub/tests/locale`). These locales should not appear unless added to `LOCALE_PATH`. If you change the `.po` files for these test locales, recompile the `.mo` files manually:

```sh
msgfmt --check-format -o django.mo django.po
```

## E2E Testing

Our project includes end-to-end (E2E) tests written in [addons-release-tests](https://github.com/mozilla/addons-release-tests) maintained by our QA team.
Further documentation on E2E testing will be provided in the future.

By following these practices and utilizing the tools provided, developers can ensure that the **addons-server** project maintains high standards of code quality and stability. For more detailed instructions on specific testing commands and configurations, refer to the project documentation and `pytest` documentation.
