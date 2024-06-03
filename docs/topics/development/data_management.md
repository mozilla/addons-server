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
