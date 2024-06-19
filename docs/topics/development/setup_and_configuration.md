# Setup and Configuration

## Local Development Environment

Setting up the local development environment for the **addons-server** involves configuring Docker Compose to run the necessary services. Follow these steps to get started:

1. **Prerequisites**:
    - Ensure Docker and Docker Compose are installed on your system.
    - Clone the **addons-server** repository from GitHub:

      ```sh
      git clone https://github.com/mozilla/addons-server
      cd addons-server
      ```

2. **Configuration**:
    - Run the following command to create the `.env` file with necessary environment variables:

      ```sh
      make setup
      ```

      This command generates the `.env` file required by our Docker Compose configuration in the `env_file` property. The `.env` file includes sensible defaults for each required value. Changes to the `.env` file will persist if you rerun `make setup`.

3. **Bringing Up Services**:
    - When running the project for the first time, execute:

      ```sh
      make initialize_docker
      ```

      This command will:
      - Run `make up` to start the Docker containers.
      - Run `make initialize` to set up the initial Docker environment, including database initialization and data population. Detailed steps for `make initialize` will be covered in Section 6 on Data Management.

4. **Understanding `make up`**:
    - The `make up` command ensures all necessary files are created on the host and starts the Docker Compose project, including volumes, containers, and networks.
    - Here’s a high-level overview of what `make up` does:

      ```sh
      up: setup docker_mysqld_volume_create docker_extract_deps docker_compose_up
      ```

      - **setup**: Creates configuration files such as `.env`.
      - **docker_mysqld_volume_create**: Ensures the MySQL volume is created.
      - **docker_extract_deps**: Installs dependencies inside the Docker container.
      - **docker_compose_up**: Starts the Docker containers defined in [docker-compose.yml][docker-compose].

5. **Accessing the Development Environment**:
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

### Configuring your environment

#### Build vs Pull

The default behaviour of running addons-server is to build the image locally with a build cache to make subsequent builds
extremely fast. You can configure your environment to run a pulled image. This can be useful if you have limited CPU
or if you want to run a very specific version of addons-server, say for testing a Pull request or debugging the version
currently in a deployed environment.

When you run `make setup` (or make up) the generated .env file determines whether the image should be built or pulled.

Running `make up` without any arguments will produce something like this. Let's look at what these values actually mean.

```bash
DOCKER_TAG=mozilla/addons-server:local
DOCKER_TARGET=development
DOCKER_PULL_POLICY=build
```

`DOCKER_TAG` specifies the precise tag of the image.
`DOCKER_TARGET` specifies which target of the image to run. Valid options are `development` or `production`.

> Running addons-server with `DOCKER_TARGET=production` will exclude development dependencies and more closely mirror
deployed environments, however some dev related functionality may stop working due to missing dependencies.

`DOCKER_PULL_POLICY` determines the build/pull behaviour of docker compose ([learn more](https://docs.docker.com/compose/compose-file/05-services/#pull_policy))

This value is normally determined internally by the DOCKER_TAG to ensure the local image is built and remote images are
pulled.

Each of these environment variables are interpolated at runtime
and subsitute areas in the [docker-compose.yml][docker-compose] file

#### Version vs Digest

The default behavior is to build the docker image locally, but if you want to run addons-server with a remote image
you can specify a docker image version to pull with:

```bash
make up DOCKER_VERSION=<version>
```

This will check dockerhub for a tag of the specified version and pull that image. As mentioned above this will also
set the `DOCKER_PULL_POLICY` to `always` to ensure frequent pulling of the image.

You can also specify a `DOCKER_DIGEST` to pull a specific build of addons-server. This can be very useful if you want
to guarantee the exact state of the image you are running. This is used in our own CI environments to ensure each job
runs with the exact same image built in the run.

```bash
make up DOCKER_DIGEST=sha256@abc123
```

If you specify both version and digest, digest as the more specific attribute takes precedence.

#### Idempotence

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

Additionally, by defininng all of the critical docker compose variables in a .env file, it means that the behaviour
of running commands via `make` or running the same command directly via the docker CLI should produce the same result.

Though it is **highly recommended to use the make commands** instead of directly calling docker in your terminal.

## Continuous Integration Environment

The **addons-server** project uses GitHub Actions to automate testing and building processes in the CI environment. Here’s an overview of the existing CI workflows and their architecture:

1. **Existing Workflows**:
    - The CI pipeline is defined in the `.github/workflows` directory. The main workflow file, typically named `ci.yml`, orchestrates the build and test processes for the project.

2. **Reusable Actions**:
    The project leverages reusable actions:
      - [build-docker](../../../.github/actions/build-docker/action.yml)
      - [run-docker](../../../.github/actions/run-docker/action.yml)

    These actions simplify the workflow definitions and ensure consistency across different jobs.

3. **Workflow Example**:
    - A typical workflow file includes steps such as checking out the repository, setting up Docker Buildx, building the Docker image, and running the tests:

      ```yaml
      name: CI
      on: [push, pull_request]
      jobs:
        build:
          runs-on: ubuntu-latest
          steps:
            - uses: actions/checkout@v2

            - name: Build Docker Image
              uses: ./.github/actions/build-docker
            - name: Run Docker Container
              uses: ./.github/actions/run-docker
      ```

    It is important to note, reusable actions cannot checkout code, so code is always checked out on the workflow.

4. **Docker Compose Files**:
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

Make sure you've run the `make initialize_docker` step as detailed in the initial setup instructions.

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
