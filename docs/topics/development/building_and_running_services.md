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

## Gotchas

Here's a list of a few of the issues you might face when using Docker.

### Can't access the web server?

Check you've created a hosts file entry pointing `olympia.test` to the relevant IP address. If containers are failing to start use `docker compose ps` to check their running status. Another way to find out what's wrong is to run `docker compose logs`.

### Getting "Programming error [table] doesn't exist"?

Make sure you've run the `make initialize_docker` step as detailed in the initial setup instructions.

### ConnectionError during initialize (Elasticsearch container fails to start)

When running `make initialize_docker` without a working Elasticsearch container, you'll get a ConnectionError. Check the logs with `docker compose logs`. If Elasticsearch is complaining about `vm.max_map_count`, run this command on your computer or your docker-machine VM:

```sh
sudo sysctl -w vm.max_map_count=262144
```

This allows processes to allocate more memory map areas.

### Connection to Elasticsearch timed out (Elasticsearch container exits with code 137)

`docker compose up -d` brings up all containers, but running `make initialize_docker` causes the Elasticsearch container to go down. Running `docker compose ps` shows `Exited (137)` against it.

Update default settings in Docker Desktop - we suggest increasing RAM limit to at least 4 GB in the Resources/Advanced section and click on "Apply and Restart".

### Port collisions (Nginx container fails to start)

If you're already running a service on port 80 or 8000 on your host machine, the `nginx` container will fail to start. This is because the `docker-compose.override.yml` file tells `nginx` to listen on port 80 and the web service to listen on port 8000 by default.

This problem will manifest itself by the services failing to start. Here's an example for the most common case of `nginx` not starting due to a collision on port 80:

```sh
ERROR: for nginx  Cannot start service nginx:.....
...Error starting userland proxy: Bind for 0.0.0.0:80: unexpected error (Failure EADDRINUSE)
ERROR: Encountered errors while bringing up the project.
```

You can check what's running on that port by using (sudo is required if you're looking at port < 1024):

```sh
sudo lsof -i :80
```

We specify the ports `nginx` listens on in the `docker-compose.override.yml` file. If you wish to override the ports you can do so by creating a new `docker-compose` config and starting the containers using that config alongside the default config.

For example, if you create a file called `docker-compose-ports.yml`:

```yaml
nginx:
  ports:
    - 8880:80
```

Next, you would stop and start the containers with the following:

```sh
docker compose stop # only needed if running
docker compose -f docker-compose.yml -f docker-compose-ports.yml up -d
```

Now the container `nginx` is listening on 8880 on the host. You can now proxy to the container `nginx` from the host `nginx` with the following `nginx` config:

```nginx
server {
    listen       80;
    server_name  olympia.test;
    location / {
        proxy_pass   http://olympia.test:8880;
    }
}
```
