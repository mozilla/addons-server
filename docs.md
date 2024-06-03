.. _acl:

====================
Access Control Lists
====================

How permissions work
--------------------

On top of that we use the ``access.models.GroupUser`` and ``Group`` to define
what access groups a user is a part of, and each group has ``rules`` defining
which permissions they grant their members, separated by ``,``.

Permissions that you can use as filters can be either explicit or general.

For example ``Admin:EditAddons`` means only someone with that permission will
validate.

If you simply require that a user has `some` permission in the `Admin` group
you can use ``Admin:%``.  The ``%`` means "any."

Similarly a user might be in a group that has explicit or general permissions.
They may have ``Admin:EditAddons`` which means they can see things with that
same permission, or things that require ``Admin:%``.

If a user has a wildcard, they will have more permissions.  For example,
``Admin:*`` means they have permission to see anything that begins with
``Admin:``.

The notion of a superuser has a permission of ``*:*`` and therefore they can
see everything.


Django Admin
------------

Django admin relies on 2 things to gate access:
- To access the admin itself, ``UserProfile.is_staff`` needs to be ``True``. Our custom implementation allows access to users with a ``@mozilla.com`` email.
- To access individual modules/apps, ``UserProfile.has_perm(perm, obj)`` and ``UserProfile.has_module_perms(app_label)`` need to return ``True``. Our custom implementation uses the ``Group`` of the current user as above, with a mapping constant called ``DJANGO_PERMISSIONS_MAPPING`` which translates Django-style permissions into our own.
.. _branching:

================
Push From Master
================

We deploy from the `master`_ branch once a week. If you commit something to master
that needs additional QA time, be sure to use a `waffle`_ feature flag.


Local Branches
--------------

Most new code is developed in local one-off branches, usually encompassing one
or two patches to fix a bug.  Upstream doesn't care how you do local
development, but we don't want to see a merge commit every time you merge a
single patch from a branch.  Merge commits make for a noisy history, which is
not fun to look at and can make it difficult to cherry-pick hotfixes to a
release branch.  We do like to see merge commits when you're committing a set
of related patches from a feature branch.  The rule of thumb is to rebase and
use fast-forward merge for single patches or a branch of unrelated bug fixes,
but to use a merge commit if you have multiple commits that form a cohesive unit.

Here are some tips on `Using topic branches and interactive rebasing effectively <http://blog.mozilla.com/webdev/2011/11/21/git-using-topic-branches-and-interactive-rebasing-effectively/>`_.

.. _master: http://github.com/mozilla/addons-server/tree/master
.. _waffle: https://github.com/jsocol/django-waffle
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
.. include:: ../../../.github/CONTRIBUTING.rst
# Data Management

Effective data management is crucial for the **addons-server** project. This section focuses on how the project handles persistent data, data snapshots, and initial data population.

## Persistent Data Volumes

The project uses persistent data volumes to store MySQL data. This ensures that data remains intact even when containers are stopped or removed. For details on how these volumes are defined, refer to the Docker Compose configuration in the repository.

## External Mounts

The use of an external mount allows for manual management of the data lifecycle. This ensures that data is preserved even if you run `make down`. By defining the MySQL data volume as external, it decouples the data lifecycle from the container lifecycle, allowing you to manually manage the data.

## Data Population

The `make initialize_docker` command handles initial data population, including creating the database, running migrations, and seeding the database.

If you already have running containers, you can just run `make initialize` to reset the database, populate data, and reindex.

- **Database Initialization**:

  ```sh
  make initialize_docker
  ```

- **Command Breakdown**:
  - **`make up`**: Starts the Docker containers.
  - **`make initialize`**: Runs database migrations and seeds the database with initial data.

The `make initialize` command, executed as part of `make initialize_docker`, performs the following steps:

1. **Create Database**: Sets up the initial database schema.
2. **Run Migrations**: Applies any pending database migrations.
3. **Seed Database**: Inserts initial data into the database.
4. **Reindex**: Rebuilds the search index in Elasticsearch.

## Exporting and Loading Data Snapshots

You can export and load data snapshots to manage data states across different environments or for backup purposes. The Makefile provides commands to facilitate this.

- **Exporting Data**:

  ```sh
  make data_export [EXPORT_DIR=<path>]
  ```

  This command creates a dump of the current MySQL database. The optional `EXPORT_DIR` argument allows you to specify a custom path for the export directory.
  The default value is a timestamp in the `backups` directory.

  The data exported will be a .sql dump of the current state of the database including any data that has been added or modified.

- **Loading Data**:

  ```sh
  make data_restore [RESTORE_DIR=<path>]
  ```

  This command restores a MySQL database from a previously exported snapshot. The optional `RESTORE_DIR` argument allows you to specify the path of the import file.
  This must be an absolute path. It defaults to the latest stored snapshot in the `backups` directory.

Refer to the Makefile for detailed instructions on these commands.

This comprehensive setup ensures that the development environment is fully prepared with the necessary data.

By following these practices, developers can manage data effectively in the **addons-server** project. The use of persistent volumes, external mounts, data snapshots, and automated data population ensures a robust and flexible data management strategy. For more detailed instructions, refer to the project's Makefile and Docker Compose configuration in the repository.
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
=============
Building Docs
=============

To simply build the docs::

    docker compose run web make docs

If you're working on the docs, use ``make loop`` to keep your built pages
up-to-date::

    make shell
    cd docs
    make loop

Open ``docs/_build/html/index.html`` in a web browser.
.. _error:

===========
Error Pages
===========

When running Django locally you get verbose error pages instead of the
standard ones. To access the HTML for the standard error pages, you can
access the urls::

    /services/403
    /services/404
    /services/500
===================
Development
===================

.. toctree::
   :maxdepth: 2

   introduction
   setup_and_configuration
   building_and_running_services
   makefile_commands
   testing_and_quality_assurance
   data_management
   dependency_management
   performance_and_optimization
   localization_and_internationalization
   troubleshooting_and_debugging
   error_pages
   style
   contributing
   branching
   vpn
   acl
   logging
   search
   docs
   waffle
   ../../../README.rst

Development
============

Welcome to the documentation for the **addons-server** project. This guide is designed to help developers quickly understand, set up, and manage the project's various services. By leveraging Docker Compose, we ensure modularity, isolation, and efficiency across development and testing environments. Here’s a concise overview of each section to get you up and running fast.

The **addons-server** uses Docker Compose to manage a multi-container setup, facilitating the handling and scaling of components like the web server, database, and search engine. BuildKit and Bake streamline the image-building process, and Docker layer caching ensures efficient builds. This documentation is organized into ten sections, providing practical instructions to help you get started quickly.

Sections Overview
=================

Introduction
============
   - **Overview**: Key features and purpose of the **addons-server** project.
   - **Architecture**: Summary of the Docker Compose-based architecture.
   - **Goals and Benefits**: Focus on modularity, isolation, and efficiency.

Setup and Configuration
========================
   - **Local Development Environment**: Steps to set up your local environment with `docker-compose.yml`.
   - **CI Environment**: Setting up the CI environment with `docker-compose.ci.yml` and GitHub Actions.
   - **Configuration Files**: Important environment variables and configuration files.

Building and Running Services
==============================
   - **Dockerfile Details**: Explanation of each stage in the Dockerfile.
   - **Build Process**: How to build Docker images using BuildKit and Bake.
   - **Managing Containers**: Commands to start, stop, and manage containers.

Makefile Commands
==================
   - **Overview**: Purpose of the Makefile in the project.
   - **Common Commands**: Key commands like `setup`, `up`, `down`, `test`, and `lint`.
   - **Specialized Commands**: Database management, debugging, and more.

Testing and Quality Assurance
==============================
   - **Testing Framework**: Overview of pytest-based testing.
   - **Running Tests**: How to run different types of tests.
   - **CI Integration**: Automating tests with GitHub Actions.

Data Management
================
   - **Database Initialization**: Setting up and managing the database.
   - **Data Export and Import**: Exporting and restoring MySQL data.
   - **Populating Data**: Scripts and commands for test data.

Dependency Management
======================
   - **Python Dependencies**: Managing Python dependencies with the Makefile and requirements files.
   - **Node.js Dependencies**: Handling Node.js dependencies with npm.

Performance and Optimization
=============================
   - **Docker Layer Caching**: Benefits and setup for Docker layer caching.
   - **Performance Testing**: Running performance tests and optimization tips.

Localization and Internationalization
======================================
   - **Locale Management**: Compiling and managing locales.
   - **Translation Management**: Handling translation strings and merging them.

Troubleshooting and Debugging
==============================
    - **Common Issues**: Solutions to common problems.
    - **Debugging Tools**: Tools and commands for effective debugging.

This guide aims to be your quick-reference manual for efficiently working with the **addons-server** pr
# Introduction# Localization and Internationalization

Localization and internationalization are important aspects of the **addons-server** project, ensuring that the application can support multiple languages and locales. This section covers the key concepts and processes for managing localization and internationalization.

## Locale Management

Locale management involves compiling and managing translation files. The **addons-server** project uses a structured approach to handle localization files efficiently.

1. **Compiling Locales**:
   - The Makefile provides commands to compile locale files, ensuring that translations are up-to-date.
   - Use the following command to compile locales:

     ```sh
     make compile_locales
     ```

2. **Managing Locale Files**:
   - Locale files are typically stored in the `locale` directory within the project.
   - The project structure ensures that all locale files are organized and easily accessible for updates and maintenance.

## Translation Management

Translation management involves handling translation strings and merging them as needed. The **addons-server** project follows best practices to ensure that translations are accurate and consistent.

1. **Handling Translation Strings**:
   - Translation strings are extracted from the source code and stored in `.po` files.
   - The `.po` file format is used to manage locale strings, providing a standard way to handle translations.

2. **Merging Translation Strings**:
   - To extract new locales from the codebase, use the following command:

     ```sh
     make extract_locales
     ```

   - This command scans the codebase and updates the `.po` files with new or changed translation strings.
   - After extraction, scripts are used to merge new or updated translation strings into the existing locale files.
   - This process ensures that all translations are properly integrated and maintained.

## Additional Tools and Practices

1. **Pontoon**:
   - The **addons-server** project uses Pontoon, Mozilla's localization service, to manage translations.
   - Pontoon provides an interface for translators to contribute translations and review changes, ensuring high-quality localization.

2. **.po File Format**:
   - The `.po` file format is a widely used standard for managing translation strings.
   - It allows for easy editing and updating of translations, facilitating collaboration among translators.

## Translating Fields on Models

The `olympia.translations` app defines a `olympia.translations.models.Translation` model, but for the most part, you shouldn't have to use that directly. When you want to create a foreign key to the `translations` table, use `olympia.translations.fields.TranslatedField`. This subclasses Django's `django.db.models.ForeignKey` to make it work with our special handling of translation rows.

### Minimal Model Example

A minimal model with translations in addons-server would look like this:

```python
from django.db import models

from olympia.amo.models import ModelBase
from olympia.translations.fields import TranslatedField, save_signal

class MyModel(ModelBase):
    description = TranslatedField()

models.signals.pre_save.connect(save_signal,
                                sender=MyModel,
                                dispatch_uid='mymodel_translations')
```

### How It Works Behind the Scenes

A `TranslatedField` is actually a `ForeignKey` to the `translations` table. To support multiple languages, we use a special feature of MySQL allowing a `ForeignKey` to point to multiple rows.

#### When Querying

Our base manager has a `_with_translations()` method that is automatically called when you instantiate a queryset. It does two things:

- Adds an extra `lang=lang` in the query to prevent query caching from returning objects in the wrong language.
- Calls `olympia.translations.transformers.get_trans()` which builds a custom SQL query to fetch translations in the current language and fallback language.

This custom query ensures that only the specified languages are considered and uses a double join with `IF`/`ELSE` for each field. The results are fetched using a slave database connection to improve performance.

#### When Setting

Every time you set a translated field to a string value, the `TranslationDescriptor` `__set__` method is called. It determines whether it's a new translation or an update to an existing translation and updates the relevant `Translation` objects accordingly. These objects are queued for saving, which happens on the `pre_save` signal to avoid foreign key constraint errors.

#### When Deleting

Deleting all translations for a field is done using `olympia.translations.models.delete_translation()`, which sets the field to `NULL` and deletes all attached translations. Deleting a specific translation is possible but not recommended due to potential issues with fallback languages and foreign key constraints.

### Ordering by a Translated Field

`olympia.translations.query.order_by_translation` allows you to order a `QuerySet` by a translated field, honoring the current and fallback locales like when querying.

By following these practices, the **addons-server** project ensures that the application can support multiple languages and locales effectively. For more detailed instructions, refer to the project's Makefile and locale management scripts in the repository.
.. _logging:

=======
Logging
=======

Logging is fun.  We all want to be lumberjacks.  My muscle-memory wants to put
``print`` statements everywhere, but it's better to use ``log.debug`` instead.
``print`` statements make mod_wsgi sad, and they're not much use in production.
Plus, ``django-debug-toolbar`` can hijack the logger and show all the log
statements generated during the last request.  When ``DEBUG = True``, all logs
will be printed to the development console where you started the server.  In
production, we're piping everything into ``mozlog``.


Configuration
-------------

The root logger is set up from ``settings_base`` in the ``src/olympia/lib``
of addons-server. It sets up sensible defaults, but you can tweak them to your liking:

Log level
~~~~~~~~~
There is no unified log level, instead every logger has it's own log level
because it depends on the context they're used in.

LOGGING
~~~~~~~
See PEP 391 for formatting help. Messages will not propagate through a
logger unless ``propagate: True`` is set.

    ::

        LOGGING = {
            'loggers': {
                'caching': {'handlers': ['null']},
            },
        }

If you want to add more to this do something like this::

        LOGGING['loggers'].update({
            'z.paypal': {
                'level': logging.DEBUG,
            },
            'z.es': {
                'handlers': ['null'],
            },
        })


Using Loggers
-------------

The ``olympia.core.logger`` package uses global objects to make the same
logging configuration available to all code loaded in the interpreter.  Loggers
are created in a pseudo-namespace structure, so app-level loggers can inherit
settings from a root logger.  olympia's root namespace is just ``"z"``, in the
interest of brevity.  In the caching package, we create a logger that inherits
the configuration by naming it ``"z.caching"``::

    import olympia.core.logger

    log = olympia.core.logger.getLogger('z.caching')

    log.debug("I'm in the caching package.")

Logs can be nested as much as you want.  Maintaining log namespaces is useful
because we can turn up the logging output for a particular section of olympia
without becoming overwhelmed with logging from all other parts.


olympia.core.logging vs. logging
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``olympia.core.logger.getLogger`` should be used everywhere.  It returns a
``LoggingAdapter`` that inserts the current user's IP address and username into
the log message. For code that lives outside the request-response cycle, it
will insert empty values, keeping the message formatting the same.

Complete logging docs: http://docs.python.org/library/logging.html
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

5. **`test`**:
   - **Purpose**: Executes the entire test suite using pytest.
   - **Usage**:

     ```sh
     make test
     ```

6. **`lint`**:
   - **Purpose**: Enforces code style and quality standards using various linters.
   - **Usage**:

     ```sh
     make lint
     ```

7. **`format`**:
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

4. **`update_deps`**:
   - **Purpose**: Updates dependencies for production and development environments. This command splits dependencies between production and development to enable efficient caching during the Docker build process.
   - **Usage**:

     ```sh
     make update_deps
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
# Performance and Optimization

Optimizing performance is essential for maintaining efficient development and deployment workflows. This section covers the key strategies and tools used in the **addons-server** project for performance and optimization.

## Docker Layer Caching

Docker layer caching is a powerful feature that significantly speeds up the build process by reusing unchanged layers. This section explains the benefits and setup for Docker layer caching in the **addons-server** project.

1. **Benefits of Docker Layer Caching**:
   - **Reduced Build Times**: By caching intermediate layers, Docker can reuse these layers in subsequent builds, reducing the overall build time.
   - **Efficient Resource Usage**: Caching helps save bandwidth and computational resources by avoiding redundant downloads and computations.
   - **Consistency**: Ensures that identical builds produce identical layers, promoting consistency across builds.

2. **Setup for Docker Layer Caching**:
   - **Build Stages**: The Dockerfile uses build stages to isolate dependency installation and other tasks. This ensures that stages are only re-executed when necessary.
   - **Cache Mounts**: The project uses `--mount=type=cache` in the Dockerfile to cache directories across builds. This is particularly useful for caching Python and npm dependencies, speeding up future builds.

   Example snippet from the Dockerfile:

   ```Dockerfile
   RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements/prod.txt
   RUN --mount=type=cache,target=/root/.npm npm install
   ```

   - **BuildKit**: Ensures BuildKit is enabled to take advantage of advanced caching features:

     ```sh
     export DOCKER_BUILDKIT=1
     ```

   - **GitHub Actions Cache**: The custom action (`./.github/actions/cache-deps`) caches the `/deps` folder, leveraging GitHub Actions cache to improve CI run times.

## Performance Testing

Performance testing is crucial for identifying bottlenecks and optimizing application performance. The **addons-server** project includes various strategies for performance testing and optimization.

1. **Running Performance Tests**:
   - The project uses `pytest` along with plugins like `pytest-split` and `pytest-xdist` to run tests in parallel, significantly reducing test times.
   - Performance-specific tests can be run to measure the responsiveness and efficiency of the application.

2. **Optimization Tips**:
   - **Parallel Testing**: Use `pytest-xdist` to run tests in parallel:

     ```sh
     pytest -n auto
     ```

   - **Test Splitting**: Use `pytest-split` to distribute tests evenly across multiple processes.
   - **Code Profiling**: Use profiling tools to identify slow functions and optimize them.
   - **Database Optimization**: Regularly monitor and optimize database queries to ensure efficient data retrieval and storage.

By implementing these performance and optimization strategies, the **addons-server** project ensures efficient and reliable builds and tests, both locally and in CI environments. For more detailed instructions, refer to the project's Dockerfile, Makefile, and GitHub Actions configurations in the repository.
.. _amo_search_explainer:

============================
How does search on AMO work?
============================

High-level overview
===================

AMO add-ons are indexed in our Elasticsearch cluster. For each search query
someone makes on AMO, we run a custom set of full-text queries against that
cluster.

Our autocomplete (that you can see when starting to type a few characters in
the search field) uses the exact same implementation as a regular search
underneath.

Rules
-----

For each search query, we apply a number of rules that attempt to find the
search terms in each add-on name, summary and description. Each rule generates
a score that depends on:

  - The frequency of the terms in the field we're looking at
  - The importance of each term in the overall index (the more common the term is across all add-ons, the less it impacts the score)
  - The length of the field (shorter fields give a higher score as the search term is considered more relevant if they make up a larger part of the field)

Each rule is also given a specific boost affecting its score, making matches
against the add-on name more important and matches against the summary or
description.

Add-on names receive special treatment: Partial or misspelled matches are
accepted to some extent while exact matches receive a significantly higher
score.

Scoring
-------

Each score for each rule is combined into a final score which we modify
depending on the add-on popularity on a logarithm scale. "Recommended" and
"By Firefox" add-ons get an additional, significant boost to their score.

Finally, results are returned according to their score in descending order.


Technical overview
==================

We store two kinds of data in the `addons` index: indexed fields that are used for search purposes, and non-indexed fields that are meant to be returned (often as-is with no transformations) by the search API (allowing us to return search results data without hitting the database). The latter is not relevant to this document.

Our search can be reached either via the API through :ref:`/api/v5/addons/search/ <addon-search>` or :ref:`/api/v5/addons/autocomplete/ <addon-autocomplete>` which are used by our frontend.


Indexing
--------

The key fields we search against are ``name``, ``summary`` and ``description``. Because all can be translated, we index them multiple times:

  - Once with the translation in the default locale of the add-on, under ``{field}``, analyzed with just the ``snowball`` analyzer for ``description`` and ``summary``, and a custom analyzer for ``name`` that applies the following filters: ``standard``, ``word_delimiter`` (a custom version with ``preserve_original`` set to ``true``), ``lowercase``, ``stop``, and ``dictionary_decompounder`` (with a specific word list) and ``unique``.
  - Once for every translation that exists for that field, using Elasticsearch language-specific analyzer if supported, under ``{field}_l10n_{analyzer}``.

In addition, for the name, we also have:
  - For all fields described above also contains a subfield called ``raw`` that holds a non-analyzed variant for exact matches in the corresponding language (stored as a ``keyword``, with a ``lowercase`` normalizer).
  - A ``name.trigram`` variant for the field in the default language, which is using a custom analyzer that depends on a ``ngram`` tokenizer (with ``min_gram=3``, ``max_gram=3`` and ``token_chars=["letter", "digit"]``).


Flow of a search query through AMO
----------------------------------

Let's assume we search on addons-frontend (not legacy) the search query hits the API and gets handled by ``AddonSearchView``, which directly queries ElasticSearch and doesn't involve the database at all.

There are a few filters that are described in the :ref:`/api/v5/addons/search/ docs <addon-search>` but most of them are not very relevant for text search queries. Examples are filters by guid, platform, category, add-on type or appversion (application version compatibility). Those filters are applied using a ``filter`` clause and shouldn't affect scoring.

Much more relevant for text searches (and this is primarily used when you use the search on the frontend) is ``SearchQueryFilter``.

It composes various rules to define a more or less usable ranking:

Primary rules
^^^^^^^^^^^^^

These are the ones using the strongest boosts, so they are only applied to the add-on name.

**Applied rules** (merged via ``should``):

1. A ``dis_max`` query with ``term`` matches on ``name_l10n_{analyzer}.raw`` and ``name.raw`` if the language of the request matches a known language-specific analyzer, or just a ``term`` query on ``name.raw`` (``boost=100.0``) otherwise - our attempt to implement exact matches
2. If we have a matching language-specific analyzer, we add a ``match`` query to ``name_l10n_{analyzer}`` (``boost=5.0``, ``operator=and``)
3. A ``phrase`` match on ``name`` that allows swapped terms (``boost=8.0``, ``slop=1``)
4. A ``match`` on ``name``, using the standard text analyzer (``boost=6.0``, ``analyzer=standard``, ``operator=and``)
5. A ``prefix`` match on ``name`` (``boost=3.0``)
6. If a query is < 20 characters long, a ``dis_max`` query (``boost=4.0``) composed of a fuzzy match on ``name`` (``boost=4.0``, ``prefix_length=2``, ``fuzziness=AUTO``, ``minimum_should_match=2<2 3<-25%``) and a ``match`` query on ``name.trigram``, with a ``minimum_should_match=66%`` to avoid noise


Secondary rules
^^^^^^^^^^^^^^^

These are the ones using the weakest boosts, they are applied to fields containing more text like description, summary and tags.

**Applied rules** (merged via ``should``):

1. Look for matches inside the summary (``boost=3.0``, ``operator=and``)
2. Look for matches inside the description (``boost=2.0``, ``operator=and``)

If the language of the request matches a known language-specific analyzer, those are made using a ``multi_match`` query using ``summary`` or ``description`` and the corresponding ``{field}_l10n_{analyzer}``, similar to how exact name matches are performed above, in order to support potential translations.


Scoring
^^^^^^^

We combine scores through a ``function_score`` query that multiplies the score by several factors:

  - A first multiplier is always applied through the ``field_value_factor`` function on ``average_daily_users`` with a ``log2p`` modifier
  - An additional ``4.0`` weight is applied if the add-on is public & non-experimental.
  - Finally, ``5.0`` weight is applied to By Firefox and Recommended add-ons.

On top of the two sets of rules above, a ``rescore`` query is applied with a ``window_size`` of ``10``. In production, we have 5 shards, so that should re-adjust the score of the top 50 results returned only. The rules used for rescoring are the same used in the secondary rules above, with just one difference: it's using ``match_phrase`` instead of ``match``, with a slop of ``10``.


General query flow
^^^^^^^^^^^^^^^^^^

 1. Fetch current translation
 2. Fetch locale specific analyzer (`List of analyzers <https://github.com/mozilla/addons-server/blob/f099b20fa0f27989009082c1f58da0f1d0a341a3/src/olympia/constants/search.py#L13-L52>`_)
 3. Apply primary and secondary *should* rules
 4. Determine the score
 5. Rescore the top 10 results per shard


See also
^^^^^^^^

  - `addons-server search ranking tests <https://github.com/mozilla/addons-server/blob/master/src/olympia/search/tests/test_search_ranking.py>`_
  - `Elasticsearch relevancy algorithm <https://www.elastic.co/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables>`_
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
.. _style:

===================
Style Guide
===================

Writing code for olympia? Awesome! Please help keep our code readable by,
whenever possible, adhering to these style conventions.


Python
------
- see https://wiki.mozilla.org/Webdev:Python


Markup
------
- ``<!DOCTYPE html>``
- double-quote attributes
- Soft tab (2 space) indentation
- Title-Case ``<label>`` tags
  - "Display Name" vs "Display name"
- to clearfix, use the class ``c`` on an element


JavaScript
----------
- Soft tabs (4 space) indentation
- Single quotes around strings (unless the string contains single quotes)
- variable names for jQuery objects start with $. for example:

  - ``var $el = $(el);``

- Element IDs and classes that are not generated by Python should be separated
  by hyphens, eg: #some-module.
- Protect all functions and objects from global scope to avoid potential name
  collisions. When exposing functions to other scripts use
  the ``z`` namespace.
- Always protect code from loading on pages it's not supposed to load on.
  For example:

::

  $(document).ready(function() {
      if ($('#something-on-your-page').length) {
          initYourCode();
      }

      function initYourCode() {
          // ...
      }
  });
# Testing and Quality Assurance

The **addons-server** project employs a comprehensive testing framework to ensure code quality and stability. This section covers the tools and practices used for testing and quality assurance.

## Code Quality and Linting

The project uses `ruff` and `prettier` to format and lint code for Python and Node.js, respectively. Ensuring your branch has properly formatted code can be done easily:

- **Ruff**: Used for linting and formatting Python code.
- **Prettier**: Used for linting and formatting Node.js code.

To format and lint your code, run:

```sh
make format
```

This command ensures that your code adheres to the project's style guidelines.

## Build Verification

Build verification is a crucial step in our CI pipeline. We run all CI checks using an actual Docker build that is nearly identical to our local build. This ensures a high level of confidence between what you develop locally and what is tested in CI.

We verify the build itself by running checks against both our Docker configurations and our Docker container. To verify your container locally, run:

```sh
make check
```

This command runs a series of checks to ensure the Docker setup and container are functioning correctly.

## Testing

The project primarily uses Python for tests, with some Node.js tests as well. Here's how to handle testing:

- **Python Tests**: The majority of the tests are written in Python.
- **Node.js Tests**: There are some tests written in Node.js.

To run specialized tests, you can shell into the container or check `Makefile-docker` for specific test commands.

### Running Tests

To run the whole test suite, use:

```sh
make test
```

- **Running Specialized Tests**: Shell into the container and run the desired test command.

```sh
make shell
make test_some_specific_test
```

To speed up test execution, you can parallelize and/or share tests. The project uses `pytest-split` and `pytest-xdist` to facilitate this. These tools allow for distributed and parallel test execution, significantly reducing test times.

- **Parallel Testing**:

```sh
pytest -n auto  # pytest-xdist
```

#### Configuration

Configuration for your unit tests is handled automatically. Ensure that the database credentials in your settings have full permissions to modify a database with `test_` prepended to it. By default, the database name is `olympia`, so the test database is `test_olympia`.

If the code you are working on is related to search, you'll want to run Elasticsearch tests. Ensure Elasticsearch is installed. See the :ref:`elasticsearch` page for details.

- To exclude Elasticsearch tests:

```sh
make test_no_es
```

- To run only Elasticsearch tests:

```sh
make test_es
```

### Using `pytest` Directly

For advanced users, you can connect to the Docker container using `make shell` and then use `pytest` directly, which allows for finer-grained control of the test suite.

```sh
pytest
```

Examples of running subsets of the test suite:

- `pytest -m es_tests` to run tests marked as `es_tests`.
- `pytest -k test_no_license` to run tests with `test_no_license` in their name.
- `pytest src/olympia/addons/tests/test_views.py::TestLicensePage::test_no_license` to run a specific test.

For more details, see the [Pytest usage documentation](http://pytest.org/en/latest/usage.html#specifying-tests-selecting-tests).

### Useful Makefile Targets

- Run all tests:

```sh
make test
```

- Rebuild the database and run tests:

```sh
make test_force_db
```

- Stop on the first test failure:

```sh
make tdd
```

- Run tests with specific arguments or specific tests:

```sh
make test ARGS='-v src/olympia/amo/tests/test_url_prefix.py::MiddlewareTest::test_get_app'
```

- Re-run only the tests that failed in the previous run:

```sh
make test_failed
```

### Writing Tests

We support two types of automated tests:

- **Unit/Functional Tests**: Most tests fall into this category. Test classes extend `django.test.TestCase` and follow standard unit testing rules, using JSON fixtures for data.
- **External Calls**: Avoid connecting to remote services in tests. Instead, mock out those calls.

### Localization Tests

If you want to test localization, add locales in the test directory (e.g., `devhub/tests/locale`). These locales should not appear unless added to `LOCALE_PATH`. If you change the `.po` files for these test locales, recompile the `.mo` files manually:

```sh
msgfmt --check-format -o django.mo django.po
```

## E2E Testing

Our project includes end-to-end (E2E) tests written in a separate repository maintained by our QA team. Further documentation on E2E testing will be provided in the future.

By following these practices and utilizing the tools provided, developers can ensure that the **addons-server** project maintains high standards of code quality and stability. For more detailed instructions on specific testing commands and configurations, refer to the project documentation and `pytest` documentation.
# Troubleshooting and Debugging

Effective troubleshooting and debugging practices are essential for maintaining and improving the **addons-server** project. This section covers common issues, their solutions, and tools for effective debugging.

## Common Issues and Solutions

1. **Containers Not Starting**:
   - **Issue**: Docker containers fail to start.
   - **Solution**: Ensure that Docker is running and that no other services are using the required ports. Use the following command to start the containers:

     ```sh
     make up
     ```

2. **Database Connection Errors**:
   - **Issue**: The application cannot connect to the MySQL database.
   - **Solution**: Verify that the MySQL container is running and that the connection details in the `.env` file are correct. Restart the MySQL container if necessary:

     ```sh
     make down
     make up
     ```

3. **Missing Dependencies**:
   - **Issue**: Missing Python or Node.js dependencies.
   - **Solution**: Ensure that all dependencies are installed by running the following command:

     ```sh
     make update_deps
     ```

4. **Locale Compilation Issues**:
   - **Issue**: Locales are not compiling correctly.
   - **Solution**: Run the locale compilation command and check for any errors:

     ```sh
     make compile_locales
     ```

5. **Permission Issues**:
   - **Issue**: Permission errors when accessing files or directories.
   - **Solution**: Ensure that the `olympia` user has the correct permissions. Use `chown` or `chmod` to adjust permissions if necessary.

## Debugging

The Docker setup uses `supervisord` to run the Django runserver. This allows you to access the management server from a shell to run things like `ipdb`.

### Using `ipdb`

To debug with `ipdb`, add a line in your code at the relevant point:

```python
import ipdb; ipdb.set_trace()
```

Next, connect to the running web container:

```sh
make debug
```

This command brings the Django management server to the foreground, allowing you to interact with `ipdb` as you normally would. To quit, type `Ctrl+c`.

Example session:

```sh
$ make debug
docker exec -t -i olympia_web_1 supervisorctl fg olympia
:/opt/rh/python27/root/usr/lib/python2.7/site-packages/celery/utils/__init__.py:93
11:02:08 py.warnings:WARNING /opt/rh/python27/root/usr/lib/python2.7/site-packages/jwt/api_jws.py:118: DeprecationWarning: The verify parameter is deprecated. Please use options instead.
'Please use options instead.', DeprecationWarning)
:/opt/rh/python27/root/usr/lib/python2.7/site-packages/jwt/api_jws.py:118
[21/Oct/2015 11:02:08] "PUT /en-US/firefox/api/v4/addons/%40unlisted/versions/0.0.5/ HTTP/1.1" 400 36
Validating models...

0 errors found
October 21, 2015 - 13:52:07
Django version 1.6.11, using settings 'settings'
Starting development server at http://0.0.0.0:8000/
Quit the server with CONTROL-C.
[21/Oct/2015 13:57:56] "GET /static/img/app-icons/16/sprite.png HTTP/1.1" 200 3810
13:58:01 py.warnings:WARNING /opt/rh/python27/root/usr/lib/python2.7/site-packages/celery/task/sets.py:23: CDeprecationWarning:
    celery.task.sets and TaskSet is deprecated and scheduled for removal in
    version 4.0. Please use "group" instead (see the Canvas section in the userguide)

"""
:/opt/rh/python27/root/usr/lib/python2.7/site-packages/celery/utils/__init__.py:93
> /code/src/olympia/browse/views.py(148)themes()
    147     import ipdb;ipdb.set_trace()
--> 148     TYPE = amo.ADDON_THEME
    149     if category is not None:

ipdb> n
> /code/src/olympia/browse/views.py(149)themes()
    148     TYPE = amo.ADDON_THEME
--> 149     if category is not None:
    150         q = Category.objects.filter(application=request.APP.id, type=TYPE)

ipdb>
```

### Logging

Logs for the Celery and Django processes can be found on your machine in the `logs` directory.

### Using the Django Debug Toolbar

The `Django Debug Toolbar` is a powerful tool for viewing various aspects of your pages, such as the view used, parameters, SQL queries, templates rendered, and their context.

To use it, see the official getting started docs: [Django Debug Toolbar Installation](https://django-debug-toolbar.readthedocs.io/en/1.4/installation.html#quick-setup)

**Note**:

- The Django Debug Toolbar can slow down the website. Mitigate this by deselecting the checkbox next to the `SQL` panel.
- Use the Django Debug Toolbar only when needed, as it affects CSP report only for your local dev environment.
- You might need to disable CSP by setting `CSP_REPORT_ONLY = True` in your local settings because the Django Debug Toolbar uses "data:" for its logo and "unsafe eval" for some panels like templates or SQL.

## Additional Debugging Tools

1. **Interactive Shell**:
   - Use the interactive shell to debug issues directly within the Docker container.
   - Access the shell with:

     ```sh
     make shell
     ```

2. **Django Shell**:
   - The Django shell is useful for inspecting and manipulating the application state at runtime.
   - Access the Django shell with:

     ```sh
     make djshell
     ```

3. **Logs**:
   - Checking logs is a crucial part of debugging. Logs for each service can be accessed using Docker Compose.
   - View logs with:

     ```sh
     docker-compose logs
     ```

4. **Database Inspection**:
   - Inspect the database directly to verify data and diagnose issues.
   - Use a MySQL client or access the MySQL container:

     ```sh
     docker-compose exec mysql mysql -u root -p
     ```

5. **Browser Developer Tools**:
   - Use browser developer tools for debugging frontend issues. Inspect network requests, view console logs, and profile performance to identify issues.

6. **VSCode Remote Containers**:
   - If you use Visual Studio Code, the Remote - Containers extension can help you develop inside the Docker container with full access to debugging tools.

## Additional Tips

1. **Ensure Containers Are Running**:
   - Always check if the Docker containers are running. If you encounter issues, restarting the containers often resolves temporary problems.

2. **Environment Variables**:
   - Double-check environment variables in the `.env` file. Incorrect values can cause configuration issues.

3. **Network Issues**:
   - Ensure that your Docker network settings are correct and that there are no conflicts with other services.

4. **Use Specific Makefiles**:
   - If you encounter issues with Makefile commands, you can force the use of a specific Makefile to ensure the correct environment is used:

     ```sh
     make -f Makefile-docker <command>
     ```

By following these troubleshooting and debugging practices, developers can effectively diagnose and resolve issues in the **addons-server** project. For more detailed instructions, refer to the project's Makefile and Docker Compose configuration in the repository.
================================
Using the VPN with docker on OSX
================================

If you need to access services behind a VPN, the docker setup should by
default allow outgoing traffic over the VPN as it does for your host.
If this isn't working you might find that it will work if you start up
the vm *after* you have started the VPN connection.

To do this simply stop the containers::

    docker compose stop

Stop the docker-machine vm::

    # Assumes you've called the vm 'addons-dev'
    docker-machine stop addons-dev

Then connect to your VPN and restart the docker vm::

    docker-machine start addons-dev

and fire up the env containers again::

    docker compose up -d
# Waffle

We use [waffle](https://waffle.readthedocs.io/en/stable/) for managing feature access in production.

## Why switches and not flags

We prefer to use [switches](https://waffle.readthedocs.io/en/stable/types/switch.html)
over flags in most cases as switches are:

- switches are simple
- switches are easy to reason about

Flags can be used if you want to do a gradual rollout a feature over time or to a subset of users.

We have a flag `2fa-enforcement-for-developers-and-special-users` in production now.

## Creating/Deleting a switch

Switches are added via database migrations.
This ensures the switch exists in all environments once the migration is run.

To create or remove a switch,
first create an empty migration in the app where your switch will live.

```bash
python ./manage.py makemigrations <app> --empty
```

### Creating a switch

add the switch in the migration

```python
from django.db import migrations

from olympia.core.db.migrations import CreateWaffleSwitch

class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_auto_20220531_2434'),
    ]

    operations = [
        CreateWaffleSwitch('foo')
    ]
```

### Deleting a switch

remove the switch in the migration

```python

from django.db import migrations

from olympia.core.db.migrations import DeleteWaffleSwitch

class Migration(migrations.Migration):

    dependencies = [
        ('app', '0001_auto_20220531_2434'),
    ]

    operations = [
        DeleteWaffleSwitch('foo')
    ]
```

## Using a switch

Use your switch in python code

```python
if waffle.switch_is_active('foo'):
    # do something
```

Use your switch in jinja2

```django
{% if waffle.switch_is_active('foo') %}
    <p>foo is active</p>
{% endif %}
```

## Testing

Testing the result of a switch being on or off is important
to ensure your switch behaves appropriately. We can override the value of a switch easily.

Override for an entire test case

```python
# Override an entire test case class
@override_switch('foo', active=True)
class TestFoo(TestCase):
    def test_bar(self):
        assert waffle.switch_is_active('foo')

    # Override an individual test method
    @override_switch('foo', active=False)
    def test_baz(self):
        assert not waffle.switch_is_active('foo')
```

## Enabling your switch

Once your switch is deployed, you can enable it in a given environment by following these steps.

1. ssh into a kubernetes pod in the environment you want to enable the switch in. ([instructions][devops])
2. run the CLI command to enable your switch ([instructions][waffle-cli])

Toggling a switch on

```bash
./manage.py waffle_switch foo on
```

Once you've ensured that it works on dev, the typical way of doing things would be to add that manage.py command
to the deploy instructions for the relevant tag.
The engineer responsible for the tag would run the command on stage,
then SRE would run it in production on deploy.

## Cleanup

After a switch is enabled for all users and is no longer needed, you can remove it by:

1. Deleting all code referring to the switch.
2. adding a migration to remove the flag.

[devops]: https://mozilla-hub.atlassian.net/wiki/spaces/FDPDT/pages/98795521/DevOps#How-to-run-./manage.py-commands-in-an-environment "Devops"
[waffle-cli]: https://waffle.readthedocs.io/en/stable/usage/cli.html#switches "Waffle CLI"
