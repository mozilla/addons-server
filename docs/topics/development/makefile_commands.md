# Makefile Commands

The Makefile for the **addons-server** project provides a convenient interface for interacting with the Docker environment and managing common development tasks. This section details the key commands and their purposes.

## Overview of Makefile

The Makefile automates various tasks, reducing the need for manual Docker and shell commands. This ensures consistency and streamlines development workflows.

## Makefile Structure

The **addons-server** project splits its Makefile configuration into three files to separate concerns between the host operating system and Docker container environments:

1. **Makefile**:
   - Acts as the main entry point and delegates commands to either `Makefile-os` or `Makefile-docker` based on the environment.

2. **Makefile-os**:
   - Contains targets designed to run on the host operating system.
   - **Gotcha**: If you run a command specified in `Makefile-os` inside the container (e.g., by running `make shell` and then the command), it might not be available because Make will ignore those commands.

3. **Makefile-docker**:
   - Contains targets designed to run inside the Docker container.
   - If you run a target defined in `Makefile-docker` from the host, Make will redirect the command to the running container by prefixing the relevant `docker-compose exec` command.

A common benefit of using Makefiles in this manner is the ability to coordinate complex behaviors that work in both local and CI environments from a single place. It also helps organize commands meant to be run on the host machine or inside a running container.

**Note**: We aim to keep the majority of logic defined within the Makefiles themselves. However, if the logic becomes overly complex, it can be defined in a `./scripts/*` file and executed via a Make command.

## Common Commands

1. **`setup`**:
   - **Purpose**: Initializes the project by creating necessary configuration files, including the `.env` file.
   - **Usage**:

     ```sh
     make setup
     ```

2. **`up`**:
   - **Purpose**: Builds the Docker image using BuildKit and Bake, and starts the containers as defined in the Docker Compose configuration.
   - **Usage**:

     ```sh
     make up
     ```

3. **`down`**:
   - **Purpose**: Stops and removes the running containers.
   - **Usage**:

     ```sh
     make down
     ```

4. **`djshell`**:
   - **Purpose**: Provides access to the Django shell within the `web` container.
   - **Usage**:

     ```sh
     make djshell
     ```

5. **`shell`**:
   - **Purpose**: Provides access to a shell within the `web` container.
   - **Usage**:

     ```sh
     make shell
     ```

6. **`test`**:
   - **Purpose**: Executes the entire test suite using pytest.
   - **Usage**:

     ```sh
     make test
     ```

7. **`lint`**:
   - **Purpose**: Enforces code style and quality standards using various linters.
   - **Usage**:

     ```sh
     make lint
     ```

8. **`format`**:
   - **Purpose**: Automatically formats the codebase according to predefined style guidelines.
   - **Usage**:

     ```sh
     make format
     ```

## Specialized Commands

1. **`data_export` and `data_restore`**:
   - **Purpose**: Facilitates exporting and restoring data from the MySQL database.
   - **Usage**:

     ```sh
     make data_export
     make data_restore
     ```

2. **`initialize_docker`**:
   - **Purpose**: Sets up the initial Docker environment, including database initialization and data population.
   - **Usage**:

     ```sh
     make initialize_docker
     ```

3. **`build_docker_image`**:
   - **Purpose**: Builds the Docker image using BuildKit and Bake.
   - **Usage**:

     ```sh
     make build_docker_image
     ```

## Forcing a Specific Makefile

You can force Make to run a specific command from a particular Makefile by specifying the file:

```sh
make -f <File> <command>
```

## Running Commands Inside the Container

If you run a target defined in `Makefile-docker` from the host, Make will redirect the command to the running container. If the containers are not running, this might fail, and you will need to ensure the containers are running by executing:

```sh
make up
```

By using these Makefile commands, developers can streamline their workflow, ensuring consistency and efficiency in their development process. For more detailed information on each command, refer to the comments and definitions within the Makefiles themselves.
