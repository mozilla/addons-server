# Dependency Management

Managing dependencies effectively is crucial for maintaining a stable and consistent development environment. The **addons-server** project uses a well-structured approach to handle Python and Node.js dependencies.

## Python Dependencies

Python dependencies are managed using the Makefile and requirements files. All dependencies are installed into the `/deps` directory, which centralizes dependency management and simplifies data mounts.

- **Environment Variables**: The project sets environment variables for Python CLIs to install dependencies in specific locations. This includes setting paths for `PIP_CACHE_DIR`, `PIP_SRC`, and others to use the `/deps` directory.

- **Caching Mechanism**: By using Docker build stages, the project isolates the stages responsible for installing dependencies. This prevents these stages from re-running unless the actual dependency files are changed. Additionally, internal Python cache folders are cached, avoiding unnecessary re-downloads of packages and saving time and bandwidth.

- **Requirements Files**:
  - **`pip.txt`**: Specifies the version of pip to guarantee consistency.
  - **`prod.txt`**: Lists dependencies used in production deployments.
  - **`dev.txt`**: Lists additional dependencies used for development.

During the docker build, the project installs both production and development dependencies. the `DOCKER_TARGET` argument
determines which set of dependencies to copy into the final image.

### Adding Python Dependencies

We use `hashin` to manage package installs. It helps you manage your `requirements.txt` file by adding hashes to ensure that the installed package versions match your expectations. `hashin` is automatically installed in local developer environments.

To add a new dependency:

```bash
hashin -r {requirements} {dependency}=={version}
```

This will add hashes and sort the requirements for you, adding comments to show any package dependencies. Check the diff and make edits to fix any issues before submitting a PR with the additions.

> NOTE: this will not install the package, only add it to the requirements file. to install run `make up` to rebuild the docker container.

### Managing Python Dependencies

We have two requirements files for Python dependencies:

- **`prod.txt`**: Dependencies required in the production environment.

  ```bash
  make update_deps_prod
  ```

- **`dev.txt`**: Dependencies used for development, linting, testing, etc.

  ```bash
  make update_deps
  ```

We use Dependabot to automatically create pull requests for updating dependencies. This is configured in the `.github/dependabot.yml` file targeting files in the `requirements` directory.

### Managing Transitive Dependencies

In local development and CI, we install packages using pip with the `--no-deps` flag to prevent pip from installing transitive dependencies. This approach gives us control over the full dependency chain, ensuring reproducible and trustworthy environments.

## Pip Dependencies

In order to determine the dependencies a given package requires you can check

```bash
pip show <package-name>
```

To see the `requirements` field which lists the dependencies. Install missing dependencies manually.

```{admonition} Note
Ensure to comment in the requirements file above transitive dependencies which direct dependency it is required by.
```

## Node.js Dependencies

Node.js dependencies are managed using npm. Similar to Python dependencies, Node.js dependencies are installed into the `/deps` directory.

- **Environment Variables**: Environment variables are set for Node.js CLIs to ensure that dependencies are installed in the `/deps` directory. This includes setting paths for `NPM_CONFIG_PREFIX` and `NPM_CACHE_DIR`.

- **Caching Mechanism**: Node.js dependencies are also cached using Docker build stages. Internal npm cache folders are cached to avoid re-downloading packages unnecessarily.

### Adding Frontend Dependencies

To add a new frontend dependency:

```bash
npm install [package]@[version] --save --save-dev --package-lock-only
```

Select either --save or --save-dev depending on whether the package is required for production or development only.

Using the additional  flag `--package-lock-only` ensures that the package is added to the `package-lock.json` file without installing it.
Installing the package on the host is not useful as we need to include it in the container. To update the container run `make up` to rebuild the docker container.

NPM is a fully-featured package manager, so you can use the standard CLI.

## Caching in Docker Build

The Dockerfile uses build stages to isolate the dependency installation process. This ensures that stages do not re-run unless the dependency files themselves change. The caching mechanism includes:

- **Dependency Cache**: Both Python and Node.js dependencies are cached in the `/deps` directory.
- **Cache Folders**: Internal cache folders for pip and npm are themselves cached to speed up the build process.

## Updating/Installing Dependencies

Our project includes both python and npm dependencies in the `/deps` directory at build time. This folder should be
considered immutable from a development perspective. File ownership is not synchronized between the host and the container
as this increases up time by multiple minutes. To update dependencies run the following command:

```bash
make up
```

This will run the steps to build and run the containers. It will reinstall dependencies based on the current state of the `requirements` and `package.json` files. This is an intentionally chosen path that results in slower updates to dependencies but faster up time.

Considering building/runnig containers is a far more common task, it makes sense to optimize for that command. Additionally,
treating the `/deps` directory as immutable allows for faster builds and a more stable/predictable development environment that cannot
deviate from the current state of the dependencies management lock files.
