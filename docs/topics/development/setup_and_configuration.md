# Setup and Configuration

This section covers how to run _addons-server_ locally. See [github actions](./github_actions.md) for running in CI.
This should be where you start if you are running _addons-server_ for the first time.
Setting up the local development environment for **addons-server** involves configuring Docker Compose to run the necessary services.
Follow these steps to get started:

## Prerequisites

- Ensure Docker and Docker Compose are installed on your system.
- Clone the **addons-server** repository from GitHub:

  ```sh
  git clone https://github.com/mozilla/addons-server
  cd addons-server
  ```

## Running the docker compose project

> TLDR; Just run `make up`.

The _make up_ command ensures all necessary files are created on the host and starts the Docker Compose project,
including volumes, containers, networks, databases and indexes.
It is meant to be run frequently whenever you want to bring your environment "up".

Here's a high-level overview of what _make up_ does:

```make
.PHONY: up
up: setup docker_pull_or_build docker_compose_up docker_clean_images docker_clean_volumes data
```

- **setup**: Creates configuration files such as `.env` and `version.json`.
- **docker_pull_or_build**: Pulls or builds the Docker image based on the image version.
- **docker_compose_up**: Starts the Docker containers defined in [docker-compose.yml][docker-compose].
- **docker_clean_images** and **docker_clean_volumes**: Cleans up unused Docker images and volumes.
- **data**: Ensures the database, seed, and index are created.

What happens if you run `make up` when your environment is already running?.
Well that depends on what is changed since the last time you ran it.
Because `make up` is {ref}`idempotent <idempotence>` it will only run the commands that are necessary to bring your environment up to date.
If nothing has changed, nothing will happen because your environment is already in the desired state.

## Shutting down your environment

> TLDR; just run `make down`

The `make down` command does almost the complete opposite of `make up`.
It stops all docker services and removes locally built images and any used volumes.

Running `make down` will free up resources on your machine and can help if your environment gets stuck in a difficult to debug state.

A common solution to many problems is to run `make down && make up`.

> NOTE: When you run make down, it will clear all volumes except the data_mysqld volume.
> This is where your database and other persisted data is stored.
> If you want to start fresh, you can delete the data_mysqld volume.

```sh
make down
make docker_mysqld_volume_remove # Remove the mysql database volume
make up
```

If you want to completely nuke your environment and start over as if you had just cloned the repo,
you can run `make clean_docker`. This will `make down` and remove all docker resources taking space on the host machine.

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

Addons-server runs via [docker-compose](./building_and_running_services.md) and can be run in a local environment or on CI.
It is highly configurable to meet the requirements for different environments and use cases.
Here are some practical ways you can configure how _addons-server_ runs.

### Build vs Pull

By default, _addons-server_ builds a [docker image](./building_and_running_services.md) tagged _local_ before running the containers as a part of `make up`.
To run _addons-server_ with the _local_ image, just run `make up` like you normally would. It is the default.

Instead of building, you can configure your environment to run a pulled image instead. To run a pulled image,
specify a {ref}`version or digest <version-vs-digest>` when calling `make up`. E.g `make up DOCKER_TAG=latest` to run
the latest published version of `addons-server`.

For typical development it is recommended to use the default built image. It is aggressively cached and most closely
reflects the current state of your local repository. Pulling a published image can be useful if you have limited CPU
or if you want to run a very specific version of addons-server for testing a Pull request
or debugging a currently deployed version.

(version-vs-digest)=
### Version vs Digest

The default behavior is to build the docker image locally, but if you want to run addons-server with a remote image
you can specify a docker image version to pull with:

```bash
make up DOCKER_TAG=<tag>
```

Version is the published tag of addons-server and corresponds to `mozilla/addons-server:<version>` in [dockerhub][addons-server-tags].

> **Important**: When using a remote image (via `DOCKER_TAG`), the `DOCKER_TARGET` must be set to 'production'.
> Running remote images in development mode is not supported and will fail validation during setup.

Specifying a version will configure docker compose to set the [pull policy] to _always_ and specify the _image_ property
in the docker compose config to pull the latest build of the specified `version`. Once you've specified a version,
subsequent calls to `make up` will pull the same version consistently {ref}`see idempotence <idempotence>` for more details.

What if you want to run an exact build of `addons-server`,
without fetching later versions that might subsequently get published to the same tag?

You can specify a `DOCKER_DIGEST` to pull a specific build of addons-server. This can be very useful if you want
to guarantee the exact state of the image you are running. This is used in our own CI environments to ensure each job
runs with the exact same image built in the run.

```bash
make up DOCKER_DIGEST=sha256@abc123
```

A docker [build digest][docker-image-digest] corresponds to the precise state of a docker image.
Think of it like a content hash, though it's a bit more complicated than that.
Specifying a build digest means you will always run the exact same version
of the image and it will not change the contents of the image.

Our [CI][ci-workflow] workflow builds and pushes a docker image on each run. To run the exact image built during a CI run,
copy the image digest from the _build_ job logs. Look for a log line like this:

```shell
#36 pushing manifest for docker.io/mozilla/addons-server:pr-22395-ci@sha256:8464804ed645e429ccb3585a50c6003fafd81bd43407d8d4ab575adb8391537d
```

The version for the above image is `pr-22395-ci` and the digest is `sha256:8464804ed645e429ccb3585a50c6003fafd81bd43407d8d4ab575adb8391537d`.
To run the specific build of the exact run for `pr-22395` you would run:

```bash
    make up DOCKER_TAG=pr-22395-ci
```

And to run exactly the version built in this run, even if it is not the latest version, you would run:

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
    make up DOCKER_TAG=banana
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
- **[docker-compose.private.yml][docker-compose-private]**: Runs addons-server with the _customs_ service that is only available to Mozilla employees

Our docker compose files rely on substituted values, all of which are included in our .env file for direct CLI compatibility.
Any referenced _${VARIABLE}_ in the docker-compose files will be replaced with the value from the .env file. We have tests
that ensure any references are included in the .env file with valid values.

This means when you run `make docker_compose_up`, the output on your machine will be exactly the same as if you ran
`docker compose up  -d --wait --remove-orphans --force-recreate --quiet-pull` directly. You **should** use make commands,
but sometimes you need to debug further what a command is running on the terminal and this architecture allows you to do that.

By following these steps, you can set up your local development environment and understand the existing CI workflows for the **addons-server** project. For more details on specific commands and configurations, refer to the upcoming sections in this documentation.

### Environment Validation

The setup process includes strict validation of environment variables to ensure a valid configuration:

| Validation Rule | Description | Required | Validation | Default | From .env file|
|----------------|-------------|----------|------------|---------|--------------|
| `DOCKER_TAG` | The full docker tag for the image, version or version+digest | false | (derived from other values) | mozilla/addons-server:local |true |
| `DOCKER_TARGET` | The target stage to build the docker image to | true | must be `production` when building an image or using a remote image | `development` for local images, `production` for remote images | true (only for local images) |

These validations help prevent configuration issues early in the setup process.

## Gotchas

Here's a list of a few of the issues you might face when setting up your development environment

### Can't access the web server?

Check you've created a hosts file entry pointing `olympia.test` to the relevant IP address.

If containers are failing to start use `docker compose ps` to check their running status.

Another way to find out what's wrong is to run `docker compose logs`.

### Getting "Programming error [table] doesn't exist"?

Make sure you've run `make up`.

### ConnectionError during initialize (elasticsearch container fails to start)

When running `make up` without a working elasticsearch container, you'll get a ConnectionError. Check the logs with `docker compose logs`. If elasticsearch is complaining about `vm.max_map_count`, run this command on your computer or your docker-machine VM:

```sh
    sudo sysctl -w vm.max_map_count=262144
```

This allows processes to allocate more [memory map areas](https://stackoverflow.com/a/11685165/4496684).

### Connection to elasticsearch timed out (elasticsearch container exits with code 137)

`docker compose up -d` brings up all containers, but running `make up` causes the elasticsearch container to go down. Running `docker compose ps` shows _Exited (137)_ against it.

Update default settings in Docker Desktop - we suggest increasing RAM limit to at least 4 GB in the Resources/Advanced section and click on "Apply and Restart".

### Port collisions (nginx container fails to start)

If you're already running a service on port 80 or 8000 on your host machine, the _nginx_ container will fail to start. This is because the `docker-compose.override.yml` file tells _nginx_ to listen on port 80 and the web service to listen on port 8000 by default.

This problem will manifest itself by the services failing to start. Here's an example for the most common case of _nginx_ not starting due to a collision on port 80:

```shell
    ERROR: for nginx  Cannot start service nginx:.....
    ...Error starting userland proxy: Bind for 0.0.0.0:80: unexpected error (Failure EADDRINUSE)
    ERROR: Encountered errors while bringing up the project.
```

You can check what's running on that port by using (sudo is required if you're looking at port < 1024):

```sh
    sudo lsof -i :80
```

We specify the ports _nginx_ listens on in the `docker-compose.override.yml` file. If you wish to override the ports you can do so by creating a new _docker-compose_ config and starting the containers using that config alongside the default config.

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

Now the container _nginx_ is listening on 8880 on the host. You can now proxy to the container _nginx_ from the host _nginx_ with the following _nginx_ config:

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
[docker-compose-private]: ../../../docker-compose.private.yml
[docker-image-digest]: https://github.com/opencontainers/.github/blob/main/docs/docs/introduction/digests.md
[addons-server-tags]: https://hub.docker.com/r/mozilla/addons-server/tags
[ci-workflow]: https://github.com/mozilla/addons-server/actions/workflows/ci.yml

### 401 during docker build step in CI

If the `build-docker` action is run it requires repository secret and permissions to be set correctly. If you see the below error:

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

### Invalid docker context

We have in the past used custom docker build contexts to build and run addons-server.
We currently use the `default` builder context so if you get this error running make up:

```bash
ERROR: run `docker context use default` to switch to default context
18306 v0.16.1-desktop.1 /Users/awagner/.docker/cli-plugins/docker-buildx buildx use default
github.com/docker/buildx/commands.runUse
	github.com/docker/buildx/commands/use.go:31
github.com/docker/buildx/commands.useCmd.func1
	github.com/docker/buildx/commands/use.go:73
github.com/docker/cli/cli-plugins/plugin.RunPlugin.func1.1.2
	github.com/docker/cli@v27.0.3+incompatible/cli-plugins/plugin/plugin.go:64
github.com/spf13/cobra.(*Command).execute
	github.com/spf13/cobra@v1.8.1/command.go:985
github.com/spf13/cobra.(*Command).ExecuteC
	github.com/spf13/cobra@v1.8.1/command.go:1117
github.com/spf13/cobra.(*Command).Execute
	github.com/spf13/cobra@v1.8.1/command.go:1041
github.com/docker/cli/cli-plugins/plugin.RunPlugin
	github.com/docker/cli@v27.0.3+incompatible/cli-plugins/plugin/plugin.go:79
main.runPlugin
	github.com/docker/buildx/cmd/buildx/main.go:67
main.main
	github.com/docker/buildx/cmd/buildx/main.go:84
runtime.main
	runtime/proc.go:271
runtime.goexit
	runtime/asm_arm64.s:1222

make[1]: *** [docker_use_builder] Error 1
make: *** [docker_pull_or_build] Error 2
```

To fix this error, run `docker context use default` to switch to the default builder context.

### Failing make up due to invalid or failing migrations

Every time you run `make up` it will run migrations. If you have failing migrations,
this will cause the make command to fail. However, if migrations are running, it means the containers are already up.

You can inspect and fix the migration and then run `make up` again to start the re-start the containers.

Inspecting the database can be done via:

```bash
make dbshell
```

### Environment validation errors during setup

If you see validation errors during `make up` like this:

```bash
Invalid items: check setup.py for validations
• DOCKER_TARGET
• DOCKER_COMMIT
• DOCKER_BUILD
```

This usually means you're trying to use a remote image (via `DOCKER_TAG`) without the required production configuration. Remember that remote images:

- Must use `DOCKER_TARGET=production`
- Require `DOCKER_COMMIT` and `DOCKER_BUILD` values

For local development, use the default local image build which has more flexible validation rules.
