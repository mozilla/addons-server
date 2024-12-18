# Setup and Configuration

This section covers how to run _addons-server_ locally. See [github actions](./github_actions.md) for running in CI.
This should be where you start if you are running _addons-server_ for the first time.

## Prerequisites

- Basic requirements
- System requirements (Docker, etc.)
- Repository setup

## Understanding the Make Up Command

The `make up` command is the primary way to start and configure your local development environment. It's designed to be idempotent, meaning you can run it multiple times safely, and it will only make necessary changes to bring your environment to the desired state.

### Overview and Purpose

The `make up` command orchestrates the entire process of setting up and running the addons-server environment. It:

- Creates necessary configuration files
- Manages Docker images and containers
- Sets up databases and indexes
- Ensures all services are healthy and ready

### The Three Phases of `make up`

The command is split into three distinct phases, each handling a specific part of the startup process:

1. **Pre-start (up_pre)**
   - Runs the setup script to create `.env` file with environment configuration
   - Determines whether to pull or build the Docker image
   - Cleans up unnecessary files and prepares the environment

2. **Start (up_start)**
   - Creates necessary Docker volumes (like `data_mysqld`)
   - Starts all Docker containers with the correct configuration
   - Optionally waits for services to be ready using health checks (controlled by `DOCKER_WAIT=true`, defaults to false as service health is verified during [initialization](#initialization-process))

3. **Post-start (up_post)**
   - Cleans up unused Docker images and volumes
   - Runs the initialization process inside the web container
   - Sets up the database, runs migrations, and creates indexes
   - Verifies all services are healthy and connected

### Dependencies and Components

The command manages several key components:

- **Docker Services**: web, worker, mysql, elasticsearch, redis, and more
- **Volumes**: Persistent storage for database and application data
- **Configuration**: Environment variables and service settings
- **Health Checks**: Ensures all services are running correctly

You can customize the behavior using various flags:

> [!NOTE]
> See [Setup Script and Configuration](#setup-script-and-configuration) for more details
> on how to customize the behavior of `make up`.

### DOCKER_VERSION and Build Targets

The `DOCKER_VERSION` setting determines how the environment is built and configured:

- When set to `local` (default):
  - Builds the image locally using the development target
  - Sets `DOCKER_TARGET=development` by default
  - See [Build Process](./building_and_running_services.md#build-process) for details

- When set to any other value:
  - Pulls the image from the registry
  - Sets `DOCKER_TARGET=production` by default
  - Can be overridden with explicit DOCKER_TARGET setting

### DOCKER_TARGET and Runtime Features

`DOCKER_TARGET` is a fundamental configuration that influences runtime behavior:

- Sets `DEV_MODE` in Django (false when target is 'production')
- Controls development features:
  - Enables debug toolbar and development apps in DEV_MODE
  - Allows fake FxA authentication in development
  - Controls static file serving behavior
- Affects how volumes are mounted and permissions are handled

The target is automatically inferred from DOCKER_VERSION but can be overridden:

```bash
make up DOCKER_TARGET=production
```

```bash
# Skip data backup/restore process
make up DATA_BACKUP_SKIP=true

# Use a specific Docker image version
make up DOCKER_VERSION=latest

# Run in production mode
make up DOCKER_TARGET=production
```

## Setup Script and Configuration

The setup script (`scripts/setup.py`) is responsible for configuring your local development environment. It manages environment variables and creates the `.env` file that both Docker Compose and the containers use for configuration.

### Environment Variables and .env File

The `.env` file serves two critical purposes:

1. Provides configuration values to Docker Compose
2. Ensures consistent behavior between `make` commands and direct Docker Compose usage

The setup script follows a strict precedence order when determining values:

1. Default values defined in the script
2. Values from an existing `.env` file
3. Values from environment variables
4. Values from make arguments

### DOCKER_TARGET and Its Impact

`DOCKER_TARGET` is a fundamental configuration that influences many other settings:

- Determines if the environment runs in `development` or `production` mode
- Influences default values for other settings (e.g., DEBUG=true in development)
- Controls which Docker build target is used (see [Build Process](./building_and_running_services.md#build-process))
- Affects how volumes are mounted and permissions are handled

The target is automatically inferred from the Docker image version but can be overridden:

```bash
make up DOCKER_TARGET=production
```

### Volume Mounting with OLYMPIA_MOUNT

The `OLYMPIA_MOUNT` setting controls how the application code is mounted in containers. Its default value matches `DOCKER_TARGET`, and it can only be configured when `DOCKER_TARGET` is set to 'production':

- **development** mode (default for local development):
  - Mounts the local directory directly
  - Enables real-time code changes
  - Preserves local file permissions
  - Cannot be overridden when DOCKER_TARGET=development to ensure proper development environment

- **production** mode:
  - Uses named volumes
  - Ensures consistent permissions
  - Better suited for CI environments
  - Can be configured to use development-style mounting if needed

This constraint exists because development environments require direct source code mounting to enable features like hot reloading, debugging, and real-time code changes. In production environments, you have the flexibility to choose the mounting style based on your needs.

### Host Mount Configuration

The setup script maps internal container values to HOST_* variables in the .env file:

```bash
HOST_UID=<your-user-id>
HOST_MOUNT=development|production
HOST_MOUNT_SOURCE=./|data_olympia_
```

The reason we use a different name in the .env file than in the input value of the setup script is to:

- prevent the original environment values from overriding the "desired" value
  in the case that the end value is different than the one the user provided
- to increase visibility of the actual value that is passed to the container
- to ensure there is only one place to set the value for the container.

We have tests, that ensure these values cannot be overriden by environment variables.

### Environment Variable Precedence

The setup script carefully manages variable precedence to ensure predictable behavior:

1. **Default Values**: Hardcoded in setup.py (e.g., DOCKER_TARGET=development for local builds)
2. **Existing .env**: Values from a previous setup
3. **Environment Variables**: Current shell environment
4. **Make Arguments**: Command-line overrides

Example of overriding values:

```bash
# Override via environment variable
export DEBUG=false
make up

# Override via make argument
make up DEBUG=false
```

### Understanding Idempotence

The `make up` command is idempotent, meaning:

1. **Consistent Results**:
   - Same input → Same output
   - Running multiple times is safe
   - Only necessary changes are made

2. **State Management**:
   - Current state is stored in `.env`
   - Previous settings are preserved
   - Explicit overrides via arguments

3. **Practical Example**:

   ```bash
   make up DOCKER_VERSION=specific-version
   make up  # Will use same version without needing to specify again
   ```

4. **Benefits**:
   - Predictable behavior
   - Safe to run repeatedly
   - Self-documenting state

### Version vs Digest

When running addons-server with a remote image, you have two options for specifying which image to use:

#### Using Version Tags

```bash
make up DOCKER_VERSION=latest
```

- Pulls the latest build for that tag
- May change if new images are published
- Good for development and testing latest changes
- Examples: `latest`, `main`, `pr-1234-ci`

#### Using Digests

```bash
make up DOCKER_DIGEST=sha256:abc123...
```

- Pulls an exact image build
- Never changes (content-addressable)
- Perfect for reproducible environments
- Used in CI for consistent testing

When both are specified, digest takes precedence as it's more specific.

## Docker Compose Architecture

The Docker Compose setup for addons-server is designed to be flexible and maintainable across different environments. The architecture is split across multiple compose files to support different use cases and environments.

### Service Configuration

The project consists of several key services:

1. **Web and Worker Services**
   - Run the main application code
   - Use the same base image but different entry points
   - Include comprehensive health checks (30s interval, 3 retries)
   - Run on `linux/amd64` platform
   - Configured with automatic restart on failure (up to 5 attempts)

2. **Nginx Service**
   - Acts as the main reverse proxy
   - Handles static file serving
   - Routes requests between frontend and backend
   - Exposes port 80 for local development
   - Configured with client upload limits and caching rules

3. **Supporting Services**
   - MySQL (version 8.0): Primary database
   - Elasticsearch (version 7.17): Search functionality
   - Redis: Caching and session storage
   - RabbitMQ: Message queue for worker tasks
   - Memcached: Additional caching layer
   - Autograph: Addon signing service

### Volume Management

The project uses a combination of named volumes and bind mounts:

1. **Service Volumes**

    These volumes are created for use by dependent services. In most cases these volumes
    are not useful or exposed to the host and prevent anonymous bind mounts from being used
    by these 3rd party containers.

   - `data_mysql`: Persistent database storage (external volume)
   - `data_redis`, `data_elastic`, `data_rabbitmq`: Service-specific data
   - `data_static_build`, `data_site_static`: Static file storage
   - `data_nginx`: Nginx configuration

2. **Local Volumes**

   These volumes are created for use by the local 1st party containers.
   These volumes map either host or docker owned directories into directories
   inside the web/worker/nginx containers.

   - Local repository mounted to `/data/olympia`
   - Dependencies directory mounted to `/deps`
   - Storage directory for media files

### Volume Constraints

1. **Mount Source Control**
   - `DOCKER_MOUNT_SOURCE` determines volume source type:
     - In development mode: Uses host bind mounts (`./`)
     - In production mode: Uses protected container volumes (`data_olympia_`)
   - This distinction ensures:
     - Development: Direct file access and real-time updates
     - Production: Consistent permissions and isolation

2. **Anonymous Volumes Prevention**
   - All volumes must be explicitly named
   - Prevents issues with:
     - Volume lifecycle management
     - Data persistence across container restarts
     - Resource cleanup
   - Tests enforce this constraint to catch configuration errors

3. **Shared Volume Management**
   - Shared volumes must be defined in the `olympia_volumes` service
   - Services using shared volumes must declare dependency on `olympia_volumes`
   - This requirement addresses several issues:
     - Race conditions during volume creation
     - Ensures volumes exist before services start
     - Maintains consistent ownership and permissions
   - Example of the pattern:

     ```yaml
     services:
       olympia_volumes:
         # because "data_shared" is used by multiple services
         # the "first" service to use it must be the "olympia_volumes" service
         volumes:
           - data_shared:/path/to/shared
       # Because worker also uses "data_shared"
       # both services must depend on olympia_volumes
       web:
         depends_on:
           - olympia_volumes
         volumes:
           - data_shared:/path/to/shared
       worker:
         depends_on:
           - olympia_volumes
         volumes:
           - data_shared:/path/to/shared
     ```

4. **Volume Type Restrictions**
   - Bind mounts: Only allowed in development mode
   - Named volumes: Required for production mode
   - Mixed mode: Only allowed when `DOCKER_TARGET=production`
   - These restrictions ensure:
     - Development environment works with local files
     - Production environment maintains isolation
     - Consistent behavior across environments

5. **Permission Management**
   - Host-mounted volumes inherit host permissions
   - Container volumes use container user permissions
   - The `olympia_volumes` service ensures consistent ownership
   - Prevents permission-related issues between services

### Network Setup

1. **Service Communication**
   - Internal service discovery using Docker DNS
   - Web service exposed on port 8001 (uwsgi)
   - Nginx routes traffic on port 80
   - Custom hostname mapping (`olympia.test`)

2. **Frontend Integration**
   - Nginx routes frontend requests to `addons-frontend:7010`
   - API requests (`/api/`) routed to the web service
   - Static files served directly by nginx

3. **Service Ports**
   - **Core Services**:
     - Nginx: Port 80 (main web traffic)
     - uWSGI: Port 8001 (application server)
     - Autograph: Port 5500 (signing service)
     - Customs: Port 10101 (scanning service)
   - **Supporting Services**:
     - Frontend: Port 7010 (addons-frontend)
     - MySQL: Internal port (not exposed)
     - Redis/Elasticsearch: Internal ports

### Health Checks

1. **Service Health Monitoring**
   - Web and worker services include built-in health checks
   - 30-second check intervals with 3 retry attempts
   - 1-second start interval for quick feedback
   - Custom health check commands per service

2. **Dependency Management**
   - Services declare dependencies using `depends_on`
   - Health checks ensure services start in correct order
   - Optional wait mode with `DOCKER_WAIT=true`

### Service Startup Control with DOCKER_WAIT

`DOCKER_WAIT` controls whether Docker Compose waits for service health checks during startup:

```bash
make up DOCKER_WAIT=true  # Wait for health checks
```

- **Wait Mode** (`true`):
  - Blocks until all services pass health checks
  - Ensures services are fully ready before initialization
  - Slower but more reliable startup
  - Best for debugging dependencies
  - Used in CI to ensure service readiness before test execution

- **Default Mode** (`false`):
  - Starts services without waiting
  - Runs health checks in background
  - Faster parallel initialization
  - Suitable for regular development

### Environment-specific Configurations

1. **Base Configuration**
   - `docker-compose.yml`: Core service definitions
   - Environment variables from `.env` file
   - Build arguments and runtime configurations

2. **Development Overrides**
   - Local development settings
   - Debug-friendly configurations
   - Real-time code reloading

3. **Private Services**
   - Optional `docker-compose.private.yml` for custom services
   - Includes customs scanner service
   - Additional worker dependencies

4. **Configuration Files**
   - `uwsgi.ini`: Application server settings
   - `nginx/addons.conf`: Reverse proxy rules
   - `autograph_localdev_config.yaml`: Signing service setup

### Resource Management

Resource management in Docker Compose is configured with specific constraints:

1. **Service Health**
   - Automatic restart on failure (max 5 attempts)
   - Health check intervals: 30 seconds
   - Startup grace period: 1 second

2. **Volume Management**
   - Named volumes for persistence
   - Explicit volume naming required
   - No anonymous volumes allowed
   - Shared volume dependencies enforced

## Initialization Process

The initialization process ensures that your development environment is properly set up with the correct database state, required services, and initial data. This process is managed by the `initialize.py` script and runs automatically during `make up`.

### Database Setup and Data Management

1. **Database Verification**
   - Checks if the `olympia` database exists and is accessible
   - Verifies database connection and permissions
   - Creates database if it doesn't exist

2. **Data State Determination**
   - Checks for existing local admin user
   - Determines whether to seed fresh data or use existing data
   - Handles data backup and restoration

3. **Data Operations**
   - **Clean Start** (`INIT_CLEAN=true`):
     - Resets database to empty state
     - Runs fresh migrations
     - Seeds with initial data

   - **Normal Operation**:
     - Runs pending migrations
     - Loads specified data backup if requested
     - Reindexes Elasticsearch if needed

### Data Seeding Process

When seeding fresh data, the system:

1. **Basic Setup**
   - Loads initial fixtures
   - Creates required database tables
   - Sets up admin user

2. **Sample Data Generation**
   - Creates sample Firefox add-ons (10 by default)
   - Creates sample Android add-ons (10 by default)
   - Generates theme examples (5 by default)
   - Sets up default add-ons for frontend development

3. **Data Preservation**
   - Creates an `_init` backup for future use
   - Includes database and storage files
   - Enables quick reset to initial state

### Service Dependencies

The initialization process verifies all required services:

1. **Core Services**
   - MySQL database
   - Elasticsearch
   - Redis cache
   - RabbitMQ message queue

2. **Application Services**
   - Web application (Django)
   - Celery worker
   - Addon signing service

3. **Health Verification**
   - Runs health checks for each service
   - Retries up to 10 times for service availability
   - Ensures proper service configuration

### Configuration Options

The initialization process can be customized with these options:

```bash
# Force clean database initialization
make initialize INIT_CLEAN=true

# Load specific data backup
make initialize INIT_LOAD=<backup_name>

# Skip database initialization and data management
make initialize DATA_BACKUP_SKIP=true
```

When `DATA_BACKUP_SKIP=true`:

- Skips all database operations (seeding, migrations, loading)
- Skips Elasticsearch indexing
- Only verifies service dependencies and runs system checks
- Default `true` in CI or when you don't need to seed/load data or run migrations

### System Checks

After initialization completes:

1. **Django System Checks**
   - Validates Django configuration
   - Verifies model integrity
   - Checks for common issues

2. **Service Health**
   - Confirms all services are responding
   - Verifies database connections
   - Checks search index status

3. **Data Verification**
   - Ensures required data is present
   - Validates initial user accounts
   - Confirms sample add-ons are available

## Additional Configuration Options

### Data Backup Configuration

The project provides built-in functionality for managing data backups and persistence. For detailed information about data management, including how to create and load backups, seed data, and manage the database lifecycle, see [Data Management](./data_management.md).

### Debug Settings

Debug mode controls several key aspects of the application:

1. **Error Handling**
   - Detailed error pages with stack traces
   - In-browser debugging information
   - SQL query logging

2. **Static File Serving**
   - Serves static files directly through Django
   - Enables Django's debug toolbar
   - Shows template debug information

3. **Development Features**
   - Enables development-specific middleware
   - Activates additional logging
   - Allows fake FxA authentication

For information on controlling debug settings, see:

- [Setup Script and Configuration](#setup-script-and-configuration)
- [DOCKER_TARGET and Runtime Features](#docker_target-and-runtime-features)

### Private Services

Additional services can be included using `docker-compose.private.yml`:

1. **Customs Scanner**
   - Optional addon scanning service
   - Requires private repository access
   - Configurable through environment variables:

     ```bash
     CUSTOMS_API_URL=http://customs:10101/
     CUSTOMS_API_KEY=customssecret
     ```

2. **Configuration**
   - Enable with `COMPOSE_FILE` setting
   - Example:

     ```bash
     make up COMPOSE_FILE=docker-compose.yml:docker-compose.private.yml
     ```

## Development Workflow

The development workflow in addons-server is built around Make commands that provide a consistent interface for common tasks. The project uses a split Makefile structure to handle both host and container operations efficiently.

### Basic Commands

1. **Environment Management**:
   - Start environment: `make up`
   - Stop environment: `make down`
   - Access shell: `make shell`
   - Access Django shell: `make djshell`

2. **Code Quality**:
   - Run all tests: `make test`
   - Run failed tests: `make test_failed`
   - Test-driven development: `make tdd` (stops on first error)
   - Format code: `make format`
   - Check code style: `make lint`

3. **Asset Management**:
   - Update static assets: `make update_assets`
   - Run JavaScript tests: `make run_js_tests`
   - Watch JavaScript tests: `make watch_js_tests`

4. **Database Operations**:
   - Access database shell: `make dbshell`
   - Export data: `make data_dump`
   - Load data: `make data_load`
   - Clean database: `make initialize INIT_CLEAN=true`

### Accessing the Development App

After setting up your environment, follow these steps to access the application:

1. **Configure Local Domain**:
   Add this entry to your `/etc/hosts` file:

   ```bash
   127.0.0.1 olympia.test
   ```

2. **Access Points**:
   - Web Application: `http://olympia.test`
   - API Endpoints: `http://olympia.test/api/`
   - Admin Interface: `http://olympia.test/admin/`

3. **Development Tools**:
   - Django Debug Toolbar (in development mode)
   - Browser Developer Tools
   - API Documentation

### Shutting Down Your Environment

The `make down` command safely stops your development environment:

```bash
make down  # Stop all services and clean up resources
```

This command:

- Stops all running containers
- Removes non-persistent volumes
- Cleans up unused images
- Preserves your database data (in `data_mysqld` volume)

For a complete reset:

```bash
make down
make docker_mysqld_volume_remove  # Optional: Remove database data
make up
```

To completely clean your environment:

```bash
make clean_docker  # Remove all Docker resources
```

### Documentation

1. **Building Docs**:

   ```bash
   make docs
   ```

2. **Live Documentation Development**:

   ```bash
   make shell
   cd docs
   make loop
   ```

   Open `docs/_build/html/index.html` in your browser.

### Debugging Tools

1. **Container Access**:
   - Regular user shell: `make shell`
   - Root user shell: `make rootshell`
   - Django debug shell: `make djshell`

2. **Service Verification**:
   - Check nginx config: `make check_nginx`
   - Verify all services: `make check`

3. **Log Access**:
   - View service logs: `docker compose logs [service]`
   - Follow logs: `docker compose logs -f [service]`

### Common Development Tasks

1. **Code Changes**:
   - Make changes in your local environment
   - Format code: `make format`
   - Run tests: `make test`
   - Verify changes: `make check`

2. **Database Management**:
   - Create fresh database: `make initialize INIT_CLEAN=true`
   - Load specific backup: `make initialize INIT_LOAD=<backup_name>`
   - Skip data operations: `make initialize DATA_BACKUP_SKIP=true`

3. **Asset Updates**:
   - Update all assets: `make update_assets`
   - Collect static files: Handled by `update_assets`
   - Generate JS translations: Included in `update_assets`

4. **Localization**:
   - Extract strings: `make extract_locales`
   - Compile translations: `make compile_locales`
   - Push changes: `make push_locales`

For more detailed information about specific commands and their options, see [Makefile Commands](./makefile_commands.md).

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

### 401 during docker build step in CI

If the `build-docker` action is run it requires repository secret and permissions to be set correctly. If you see the below error:

```bash
Error: buildx bake failed with: ERROR: failed to solve: failed to push mozilla/addons-server:pr-22446-ci: failed to authorize: failed to fetch oauth token: unexpected status from GET request to https://auth.docker.io/token?scope=repository%3Amozilla%2Faddons-server%3Apull%2Cpush&service=registry.docker.io: 401 Unauthorized
```

See the [workflow example](./github_actions.md) for correct usage.

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
