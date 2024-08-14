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

In the Docker build, only production dependencies are included. When running `make up`, the following command is executed to install development dependencies:

```sh
make docker_extract_deps
```

This command installs the development dependencies inside the container, ensuring the development environment is fully set up.

### Adding Python Dependencies

We use `hashin` to manage package installs. It helps you manage your `requirements.txt` file by adding hashes to ensure that the installed package versions match your expectations. `hashin` is automatically installed in local developer environments.

To add a new dependency:

```bash
hashin -r {requirements} {dependency}=={version}
```

This will add hashes and sort the requirements for you, adding comments to show any package dependencies. Check the diff and make edits to fix any issues before submitting a PR with the additions.

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
npm install [package]@[version] --save --save-dev
```

NPM is a fully-featured package manager, so you can use the standard CLI.

## Caching in Docker Build

The Dockerfile uses build stages to isolate the dependency installation process. This ensures that stages do not re-run unless the dependency files themselves change. The caching mechanism includes:

- **Dependency Cache**: Both Python and Node.js dependencies are cached in the `/deps` directory.
- **Cache Folders**: Internal cache folders for pip and npm are themselves cached to speed up the build process.

## GitHub Actions Cache

The project uses a custom GitHub Actions action (`./.github/actions/cache-deps`) to cache the `/deps` folder. This action significantly increases install times for CI runs by leveraging the GitHub Actions cache.

```yaml
- name: Cache dependencies
  uses: ./.github/actions/cache-deps
```

By caching the `/deps` folder, the project ensures that dependencies are quickly restored in CI environments, reducing overall build and test times.

## Updating/Installing Dependencies

To update/install all dependencies, run the following command:

```bash
make update_deps
```

This will install all Python and frontend dependencies. By default, this command runs in a Docker container, but you can run it on the host by targeting the Makefile-docker:

```bash
make -f Makefile-docker update_deps
```

This method is used in GitHub Actions that do not need a full container to run.

**Note**: If you are adding a new dependency, make sure to update static assets imported from the new versions:

```bash
make update_assets
```

By following these practices, the **addons-server** project ensures efficient and reliable dependency management, both locally and in CI environments. For more detailed instructions, refer to the project's Makefile and Dockerfile configurations in the repository.
