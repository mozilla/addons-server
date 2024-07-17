# Setup and Configuration

This section covers how to run `addons-server` locally. See [github actions](./github_actions.md) for running in CI.
This should be where you start if you are running `addons-server` for the first time.
Setting up the local development environment for **addons-server** involves configuring Docker Compose to run the necessary services.
Follow these steps to get started:

## Prerequisites

- Ensure Docker and Docker Compose are installed on your system.
- Clone the **addons-server** repository from GitHub:

  ```sh
  git clone https://github.com/mozilla/addons-server
  cd addons-server
  ```

(running-for-the-first-time)=
## Running for the first time

When running the project for the first time, execute:

```sh
make initialize_docker
```

This command will run:

- `make up` to start the Docker containers.
- `make initialize` to set up the initial Docker environment, including database initialization and data population.
Detailed steps for `make initialize` will be covered in Section 6 on Data Management.

If you run `make up` without running `make initialize` the docker compose services will be running, but you will not have a database
and the app might crash or otherwise be unusable.

Similarly, you can run `make initialize` even after you have an up and running environment, but this will totally reset your database
as if you were running the application fresh.

## Updating your environment

> TLDR; Just run `make up`.

The `make up` command ensures all necessary files are created on the host and starts the Docker Compose project,
including volumes, containers, and networks. It is meant to be run frequently whenever you want to bring your environment "up".

Here’s a high-level overview of what `make up` does:

```yaml
up: setup docker_mysqld_volume_create docker_extract_deps docker_compose_up
```

- **setup**: Creates configuration files such as `.env`.
- **docker_mysqld_volume_create**: Ensures the MySQL volume is created.
- **docker_extract_deps**: Installs dependencies inside the Docker container.
- **docker_compose_up**: Starts the Docker containers defined in [docker-compose.yml][docker-compose].

What happens if you run `make up` when your environment is already running?
This will result in all services and volumes being recreated as if starting them for the first time,
and will clear any local state from the containers. The `make up` command is {ref}`idempotent <idempotence>` so you can run it over and over.

## Shutting down your environment

> TLDR; just run `make down`

The `make down` command does almost the complete opposite of `make up`.
It stops all docker services and removes locally built images and any used volumes.

Running `make down` will free up resources on your machine and can help if your environment gets stuck in a difficult to debug state.

A common solution to many problems is to run `make down && make up`.

### Accessing the Development App

- Add the following entry to your `/etc/hosts` file to access **addons-server** via a local domain:

  ```sh
  127.0.0.1 olympia.test
  ```

- The web application should now be accessible at `http://olympia.test`.
- You can access the web container for debugging and development:

  ```sh
  make shell
  ```

- To access the Django shell within the container:

  ```sh
  make djshell
  ```

## Configuring your environment

Addons-server runs via docker-compose and can be run in a local environment or on CI. It is highly configurable to meet
the requirements for different environments and use cases. Here are some practical ways you can configure how `addons-server` runs.

### Build vs Pull

By default, `addons-server` builds a [docker image](./docker.md) tagged `local` before running the containers as a part of `make up`.
To run `addons-server` with the `local` image, just run `make up` like you normally would. It is the default.

Instead of building, you can configure your environment to run a pulled image instead. To run a pulled image,
specify a {ref}`version or digest <version-vs-digest>` when calling `make up`. E.g `make up DOCKER_VERSION=latest` to run
the latest published version of `addons-server`.

For typical development it is recommended to use the default built image. It is aggresively cached and most closely
reflects the current state of your local repository. Pulling a published image can be useful if you have limited CPU
or if you want to run a very specific version of addons-server for testing a Pull request
or debugging a currently deployed version.

(version-vs-digest)=
### Version vs Digest

The default behavior is to build the docker image locally, but if you want to run addons-server with a remote image
you can specify a docker image version to pull with:

```bash
make up DOCKER_VERSION=<version>
```

Version is the published tag of addons-server and corresponds to `mozilla/addons-server:<version>`in [dockerhub][addons-server-tags].

Specify a version will configure docker compose to set the [pull policy] to `always` and specify the `image` property
in the docker compose config to pull the latest build of the specified `version`. Once, you've specified a version
subsequent calls to `make up` will pull the same version consistently {ref}`see idempotence <idempotence>` for more details.

What if you want to run an exact build of `addons-server`,
without fetching later versions that might subsequently get published to the same tag?

You can specify a `DOCKER_DIGEST` to pull a specific build of addons-server. This can be very useful if you want
to guarantee the exact state of the image you are running. This is used in our own CI environments to ensure each job
runs with the exact same image built in the run.

```bash
make up DOCKER_DIGEST=sha256@abc123
```

A docker [build digest][docker-image-digest] corresponds to the precies state of a docker image.
Think of it like a content hash, though it's a bit more complicated than that.
Specifying a build digest means you will always run the exact same version
of the image and it will not change the contents of the image.

Our [CI][ci-workflow] workflow builds and pushes a docker image on each run. To run the exact image built during a CI run,
copy the image digest from the `build` job logs. Look for a log line like this:

```shell
#36 pushing manifest for docker.io/mozilla/addons-server:pr-22395-ci@sha256:8464804ed645e429ccb3585a50c6003fafd81bd43407d8d4ab575adb8391537d
```

The version for the above image is `pr-22395-ci` and the digest is `sha256:8464804ed645e429ccb3585a50c6003fafd81bd43407d8d4ab575adb8391537d`.
To run the specific build of the exact run for `pr-22395` you would run:

```bash
    make up DOCKER_VERSION=pr-22395-ci
```

And to run, exactly the version built in this run, even if it is not the latest version, you would run:

```bash
    make up DOCKER_DIGEST=sha256:8464804ed645e429ccb3585a50c6003fafd81bd43407d8d4ab575adb8391537d
```

If you specify both a version and digest, digest as the more specific attribute takes precedence.

(idempotence)=
### Idempotence

The `make up` command and all of its sub-commands are idempotent.
That means if the command is repeated with the same inputs you will always get the same result.
If you run

```bash
    make up DOCKER_VERSION=banana
```

and then run make up again, the .env file will have a docker tag specifying the version `banana`.
This prevents you from needing to constantly specify parameters over and over.
But it also means you have to remember what values you have set for different properties as they can have huge
impacts on what is actually running in your environment.

`make up` logs the current environment specifications to the terminal as it is running so you should always know
what exactly is happening in your environment at any given time.

Additionally, by defining all of the critical docker compose variables in a .env file, it means that the behaviour
of running commands via `make` or running the same command directly via the docker CLI should produce the same result.

Though it is **highly recommended to use the make commands** instead of directly calling docker in your terminal.

### Docker Compose Files

- **[docker-compose.yml][docker-compose]**: The primary Docker Compose file defining services, networks, and volumes for local and CI environments.
- **[docker-compose.ci.yml][docker-compose-ci]**: Overrides certain configurations for CI-specific needs, ensuring the environment is optimized for automated testing and builds.
- **[docker-compose.deps.yml][docker-compose-deps]**: Attaches a mount at ./deps to /deps in the container, exposing the contents to the host
- **[docker-compose.private.yml][docker-compose-private]**: Runs addons-server with the `customs` service that is only avaiable to Mozilla employees

Our docker compose files rely on substituted values, all of which are included in our .env file for direct CLI compatibility.
Any referenced `${VARIABLE}` in the docker-compose files will be replaced with the value from the .env file. We have tests
that ensure any references are included in the .env file with valid values.

This means when you run `make docker_compose_up`, the output on your machine will be exactly the same is if you ran
`docker compose up  -d --wait --remove-orphans --force-recreate --quiet-pull` directly. You **should** use make commands,
but sometimes you need to debug further what a command is running on the terminal and this architecture allows you to do that.

By following these steps, you can set up your local development environment and understand the existing CI workflows for the **addons-server** project. For more details on specific commands and configurations, refer to the upcoming sections in this documentation.

## Gotchas

Here's a list of a few of the issues you might face when setting up your development environment

### Can't access the web server?

Check you've created a hosts file entry pointing `olympia.test` to the relevant IP address.

If containers are failing to start use `docker compose ps` to check their running status.

Another way to find out what's wrong is to run `docker compose logs`.

### Getting "Programming error [table] doesn't exist"?

Make sure you've run the `make initialize_docker` step as {ref}`detailed <running-for-the-first-time>` in the initial setup instructions.

### ConnectionError during initialize (elasticsearch container fails to start)

When running `make initialize_docker` without a working elasticsearch container, you'll get a ConnectionError. Check the logs with `docker compose logs`. If elasticsearch is complaining about `vm.max_map_count`, run this command on your computer or your docker-machine VM:

```sh
    sudo sysctl -w vm.max_map_count=262144
```

This allows processes to allocate more [memory map areas](https://stackoverflow.com/a/11685165/4496684).

### Connection to elasticsearch timed out (elasticsearch container exits with code 137)

`docker compose up -d` brings up all containers, but running `make initialize_docker` causes the elasticsearch container to go down. Running `docker compose ps` shows `Exited (137)` against it.

Update default settings in Docker Desktop - we suggest increasing RAM limit to at least 4 GB in the Resources/Advanced section and click on "Apply and Restart".

### Port collisions (nginx container fails to start)

If you're already running a service on port 80 or 8000 on your host machine, the `nginx` container will fail to start. This is because the `docker-compose.override.yml` file tells `nginx` to listen on port 80 and the web service to listen on port 8000 by default.

This problem will manifest itself by the services failing to start. Here's an example for the most common case of `nginx` not starting due to a collision on port 80:

```shell
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

### returned Internal Server Error for API route and version

This can occur if the docker daemon has crashed. Running docker commands will return errors as the CLI cannot communicate
with the daemon. The best thing to do is to restart docker and to check your docker memory usage. The most likely cause
is limited memory. You can check the make commands to see how you can free up space on your machine.

```bash
    docker volume create addons-server_data_mysqld
    request returned Internal Server Error for API route and version http://%2FUsers%2Fwilliam%2F.docker%2Frun%2Fdocker.sock/v1.45/volumes/create, check if the server supports the requested API version
    make: *** [docker_mysqld_volume_create] Error 1
```

### Mysqld failing to start

Our MYSQLD service relies on a persistent data volume in order to save the database even after containers are removed.
It is possible that the volume is in an incorrect state during startup which can lead to erros like the following:

```bash
    mysqld-1  | 2024-06-14T13:50:33.169411Z 0 [ERROR] [MY-010457] [Server] --initialize specified but the data directory has files in it. Aborting.
    mysqld-1  | 2024-06-14T13:50:33.169416Z 0 [ERROR] [MY-013236] [Server] The designated data directory /var/lib/mysql/ is unusable. You can remove all files that the server added to it.
```

The best way around this is to `make down && make up` This will prune volumes and restart addons-server.

### stat /Users/kmeinhardt/src/mozilla/addons-server/env: no such file or directory

If you ran into this issue, it is likely due to an invalid .env likely created via running tests for our makefile
and docker-comose.yml file locally.

```bash
    docker compose up  -d --wait --remove-orphans --force-recreate --quiet-pull
    stat /Users/kmeinhardt/src/mozilla/addons-server/env: no such file or directory
    make: *** [docker_compose_up] Error 14
```

To fix this error `rm -f .env` to remove your .env and `make up` to restart the containers.

[docker-compose]: ../../../docker-compose.yml
[docker-compose-ci]: ../../../docker-compose.ci.yml
[docker-compose-deps]: ../../../docker-compose.deps.yml
[docker-compose-private]: ../../../docker-compose.private.yml
[docker-image-digest]: https://github.com/opencontainers/.github/blob/main/docs/docs/introduction/digests.md
[addons-server-tags]: https://hub.docker.com/r/mozilla/addons-server/tags
[ci-workflow]: https://github.com/mozilla/addons-server/actions/workflows/ci.yml

### 401 during docker build step in CI

If the `_build.yml` workflow is run it requires repository secret and permissions to be set correctly. If you see the below error:

```bash
Error: buildx bake failed with: ERROR: failed to solve: failed to push mozilla/addons-server:pr-22446-ci: failed to authorize: failed to fetch oauth token: unexpected status from GET request to https://auth.docker.io/token?scope=repository%3Amozilla%2Faddons-server%3Apull%2Cpush&service=registry.docker.io: 401 Unauthorized
```

See the (workflow example)[./github_actions.md] for correct usage.

### Invalid pull_policy

If you run docker compose commands directly in the terminal, it is critical that your `.env` file exists and is up to date. This is handled automatically using make commands
but if you run `docker compose pull` without a .env file, you may encounter validation errors. That is because our docker-compose file itself uses variable substituation
for certain properties. This allows us to modify the behaviour of docker at runtime.

```bash
validating /Users/user/mozilla/addons-server/docker-compose.yml: services.worker.pull_policy services.worker.pull_policy must be one of the following: "always", "never", "if_not_present", "build", "missing"
```

To fix this error, run `make setup` to ensure you have an up-to-date .env file locally.
