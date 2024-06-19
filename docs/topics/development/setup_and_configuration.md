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
      - **docker_compose_up**: Starts the Docker containers defined in `docker-compose.yml`.

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

## Continuous Integration Environment

The **addons-server** project uses GitHub Actions to automate testing and building processes in the CI environment. Here’s an overview of the existing CI workflows and their architecture:

1. **Existing Workflows**:
    - The CI pipeline is defined in the `.github/workflows` directory. The main workflow file, typically named `ci.yml`, orchestrates the build and test processes for the project.

2. **Reusable Actions**:
    - The project leverages reusable actions located in `./.github/actions/build-docker` and `./.github/actions/run-docker`. These actions simplify the workflow definitions and ensure consistency across different jobs.

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
    - **`docker-compose.yml`**: The primary Docker Compose file defining services, networks, and volumes for local and CI environments.
    - **`docker-compose.ci.yml`**: Overrides certain configurations for CI-specific needs, ensuring the environment is optimized for automated testing and builds.

Our docker compose files rely on substituted values, all of which are included in our .env file for direct CLI compatibility.
Any referenced `${VARIABLE}` in the docker-compose files will be replaced with the value from the .env file. We have tests
that ensure any references are included in the .env file with valid values.

This means when you run `make docker_compose_up`, the output on your machine will be exactly the same is if you ran
`docker compose up  -d --wait --remove-orphans --force-recreate --quiet-pull` directly. You **should** use make commands,
but sometimes you need to debug further what a command is running on the terminal and this architecture allows you to do that.

By following these steps, you can set up your local development environment and understand the existing CI workflows for the **addons-server** project. For more details on specific commands and configurations, refer to the upcoming sections in this documentation.
