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

## Node.js Dependencies

Node.js dependencies are managed using npm. Similar to Python dependencies, Node.js dependencies are installed into the `/deps` directory.

- **Environment Variables**: Environment variables are set for Node.js CLIs to ensure that dependencies are installed in the `/deps` directory. This includes setting paths for `NPM_CONFIG_PREFIX` and `NPM_CACHE_DIR`.

- **Caching Mechanism**: Node.js dependencies are also cached using Docker build stages. Internal npm cache folders are cached to avoid re-downloading packages unnecessarily.

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

By following these practices, the **addons-server** project ensures efficient and reliable dependency management, both locally and in CI environments. For more detailed instructions, refer to the project's Makefile and Dockerfile configurations in the repository.
