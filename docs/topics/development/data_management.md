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

You can export and load data snapshots to manage data states across different environments or for backup purposes.
The Makefile provides commands to facilitate this.
These commands rely internally on [django-dbbackup](https://django-dbbackup.readthedocs.io/en/stable/)

- **Data dump**:

  ```sh
  make data_dump [ARGS="--name <name> --force"]
  ```

  This command creates a dump of the current MySQL database. The command accepts an optional `name` argument which will determine
  the name of the directory created in the `DATA_BACKUP_DIRNAME` directory. By default it uses a timestamp to ensure uniqueness.

  You can also specify the `--force` argument to overwrite an existing backup with the same name.

- **Loading Data**:

  ```sh
  make data_load [ARGS="--name <name>"]
  ```

  This command will load data from an existing backup directory, synchronize the storage directory and reindex elasticsearch.
  The name is required and must match a directory in the `DATA_BACKUP_DIRNAME` directory.


## Hard Reset Database

The actual mysql database is created and managed by the `mysqld` container. The database is created on container start
and the actual data is stored in a persistent data volume. This enables data to persist across container restarts.

`addons-server` assumes that a database named `olympia` already exists and most data management commands will fail
if it does not.

If you need to hard reset the database (for example, to start with a fresh state), you can use the following command:

```bash
make down && docker_mysqld_volume_remove
```

This will stop the containers and remove the `mysqld` data volume from docker. The next time you run `make up` it will
create a new empty volume for you and mysql will recreate the database.

> NOTE: removing the data volume will remove the actual data! You can and should save a backup before doing this
> if you want to keep the data.
