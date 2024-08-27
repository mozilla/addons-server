# Building and Running Services

## Dockerfile Details

The Dockerfile for the **addons-server** project uses a multi-stage build to optimize the image creation process. Here’s an overview of the key concepts and design decisions behind it:

1. **Multi-Stage Build**:
   - **Intent**: Multi-stage builds allow Docker to parallelize steps that don't depend on each other and to better cache between layers. This results in more efficient builds by reducing the size of the final image and reusing intermediate layers.
   - **Layer Caching**: The use of `--mount=type=cache` arguments helps cache directories across builds, particularly useful for node and pip dependencies, dramatically speeding up future builds.

2. **OLYMPIA_USER**:
   - **Creating a Non-Root User**: The Dockerfile creates an `olympia` user to run the application. This allows the container to run processes as a non-root user, enhancing security by preventing privilege escalation.
   - **Why Non-Root?**: Running containers as root is considered an antipattern for Python projects due to security vulnerabilities. Using a non-root user like `olympia` ensures that even if an attacker accesses the container, they cannot escalate privileges to the host.

3. **Mounts in Docker Compose**:
   - **Mounting Local Repository**: The volume `.:/data/olympia` mounts the local Git repository into the container, allowing real-time changes to files within the container.
   - **Mounting Dependencies**: The volume `./deps:/deps` mounts the dependencies directory, enabling better caching across builds and providing visibility for debugging directly on the host.

4. **Environment Variables for OLYMPIA_USER**:
   - **Development Setup**: The `HOST_UID` environment variable is set to the host user ID, ensuring that the container runs with the correct permissions.
   - **CI Setup**: In CI environments, such as defined in `docker-compose.ci.yml`, the user ID is reset to the default 9500, and the Olympia mount is removed. This makes the container a closed system, mimicking production behavior closely.

### Best Practices for the Dockerfile

- **Use as Few Instructions as Possible**: This minimizes the size of the image and reduces build times.
- **Split Long-Running Tasks**: Distinct stages improve caching and concurrency.
- **Prefer `--mount=type=bind` Over `COPY`**: Use bind mounts for files needed for a single command. Bind mounts do not persist data, so modified files will not be in the final layer.
- **Prefer Copying Individual Files Over Directories**: This reduces the likelihood of false cache hits.
- **Use `--mount=type=cache` for Caching**: Cache npm/pip dependencies to speed up builds.
- **Delay Copying Source Files**: This improves cache validity by ensuring that as many stages as possible can be cached.

## Build Process

The **addons-server** project uses BuildKit and Bake to streamline the image-building process.

1. **BuildKit**:
   - **Overview**: BuildKit is a modern Docker image builder that enhances performance, scalability, and extensibility. It allows for parallel build steps, caching, and improved efficiency.
   - **Enabling BuildKit**: Ensure BuildKit is enabled by setting the environment variable `DOCKER_BUILDKIT=1`.

2. **Bake**:
   - **Overview**: Docker Bake is a tool for defining and executing complex build workflows. It simplifies multi-platform builds and allows for more granular control over the build process.
   - **Using Bake**: We use Bake to enable building via Docker Compose consistently across local and CI builds. The `build` target in the `docker-compose.yml` file defines the build context and Dockerfile for the addons-server image.

To build the Docker images for the project, use the following command:

```sh
make build_docker_image
```

This command leverages BuildKit and Bake to efficiently build the required images.

### Clearing Cache

To clear the custom builder cache used for buildkit mount caching:

```bash
docker builder prune
```

Avoid using `docker system prune` as it does not clear the specific builder cache.

## Managing Containers

Managing the Docker containers for the **addons-server** project involves using Makefile commands to start, stop, and interact with the services.

1. **Starting Services**:
   - Use `make up` to start the Docker containers:

     ```sh
     make up
     ```

   - This command ensures all necessary files are created and the Docker Compose project is running.

2. **Stopping Services**:
   - Use `make down` to stop and remove the Docker containers:

     ```sh
     make down
     ```

3. **Accessing Containers**:
   - Access the web container for debugging:

     ```sh
     make shell
     ```

   - Access the Django shell within the container:

     ```sh
     make djshell
     ```

4. **Rebuilding Images**:
   - Use `make up` to rebuild the Docker images if you make changes to the Dockerfile or dependencies. Remember, `make up` is idempotent, ensuring your image is built and running based on the latest changes.

This section provides a thorough understanding of the Dockerfile stages, build process using BuildKit and Bake, and commands to manage the Docker containers for the **addons-server** project. For more detailed information on specific commands, refer to the project's Makefile and Docker Compose configuration in the repository.

## Docker Compose

We use docker compose under the hood to orchestrate container both locally and in CI.
The `docker-compose.yml` file defines the services, volumes, and networks required for the project.

Our docker compose project is split into a root [docker-compose.yml](../../../docker-compose.yml) file and additional files for specific environments,
such as [docker-compose.ci.yml](../../../docker-compose.ci.yml) for CI environments.

### Healthchecks

We define healthchecks for the web and worker services to ensure that the containers are healthy and ready to accept traffic.
The health checks ensure the django wsgi server and celery worker node are running and available to accept requests.

### Environment specific compose files

- **Local Development**: The `docker-compose.yml` file is used for local development. It defines services like `web`, `db`, `redis`, and `elasticsearch`.
- **CI Environment**: The `docker-compose.ci.yml` file is used for CI environments. It overrides the HOST_UID as well as removing volumes to make the container more production like.
- **Private**: This file includes the customs service that is not open source and should therefore not be included by default.
- **Override**: This file allows modifying the default configuration without changing the main `docker-compose.yml` file. This file is larglely obsolete and should not be used.

To mount with a specific  set of docker compose files you can add the COMPOSE_FILE argument to make up. This will persist your setting to .env.

```sh
make up COMPOSE_FILE=docker-compose.yml:docker-compose.ci.yml
```

Files should be separated with a colon.

### Volumes

Our project defines volumes to mount and share local data between services.

- **data_redis,data_elastic,data_rabbitmq**: Used to persist service specific data in a named volume to avoid anonymous volumes in our project.
- **data_mysql**: Used to persist the MySQL data in a named volume to avoid anonymous volumes in our project.
Additionally this volume is "external" to allow the volume to persist across container lifecycle. If you make down, the data will not be destroyed.
- **storage**: Used to persist local media files to nginx.

We additionally mount serval local directories to the web/worker containers.

- **.:/data/olympia**: Mounts the local repository into the container to allow real-time changes to files within the container.
- **./deps:/deps**: Mounts the dependencies directory to enable better caching across builds and provide visibility for debugging directly on the host.
