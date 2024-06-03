# Testing and Quality Assurance

The **addons-server** project employs a comprehensive testing framework to ensure code quality and stability. This section covers the tools and practices used for testing and quality assurance.

## Code Quality and Linting

The project uses `ruff` and `prettier` to format and lint code for Python and Node.js, respectively. Ensuring your branch has properly formatted code can be done easily:

- **Ruff**: Used for linting and formatting Python code.
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

- **Running Tests**:

  ```sh
  make test
  ```

- **Running Specialized Tests**:
  Shell into the container and run the desired test command.

  ```sh
  make shell
  make test_some_specific_test
  ```

To speed up test execution, you can parallelize and/or share tests. The project uses `pytest-split` and `pytest-xdist` to facilitate this. These tools allow for distributed and parallel test execution, significantly reducing test times.

- **Parallel Testing**:

  ```sh
  pytest -n auto  # pytest-xdist
  ```

## E2E Testing

Our project includes end-to-end (E2E) tests written in a separate repository maintained by our QA team. Further documentation on E2E testing will be provided in the future.

By following these practices and utilizing the tools provided, developers can ensure that the **addons-server** project maintains high standards of code quality and stability. For more detailed information on specific testing commands and configurations, refer to the project documentation and `pytest` documentation.
