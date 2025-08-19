# Database

Information about the database and how to work with it.

## Migrations

MySQL does not support transactional DDL (Data Definition Language statements like `ALTER TABLE`, `CREATE TABLE`, etc.).

Therefore, Django migrations run against MySQL are not truly atomic, even if `atomic = True` is set on the migration class.

Here's what that means:

- Implicit Commits: MySQL automatically commits the transaction before and after most DDL statements.
- Partial Application: If a migration involves multiple operations (e.g., adding a field, then creating an index) and fails during the second operation, the first operation (adding the field) will not be rolled back automatically. The database schema will be left in an intermediate state.
- `atomic = True` Limitation: While Django attempts to wrap the migration in a transaction, the underlying database behavior with DDL prevents full atomicity for schema changes in MySQL. DML operations (like `RunPython` or data migrations) within that transaction might be rolled back, but the DDL changes won't be.

### Writing migrations

Keep these tips in mind when writing migrations:

1. Always create a migration via `./manage.py makemigrations`

   This ensures that the migration is created with the correct dependencies, sequential naming etc. (to create an empty migration that executes arbitrary code, use `./manage.py makemigrations --empty <name>`).

2. If you need to execute arbitrary code, use `RunPython` or `RunSQL` operations.

   These operations are not wrapped in a transaction, so you need to be careful with how you write them and be mindful that the state of the database might not be consistent every time the migration is run. Validate assumptions and be careful.

   If your migration requires `RunPython`, make that the only operation in the migration. Split database table modification to a separate migration to ensure a partial application due to failure does not result in an invalid database state.

3. Large data migrations should be run via `tasks`

   This ensures they run on an environment that supports long running work. In production (kubernetes) pods are disposable, so you should not assume you can run a long migration in an arbitrary pod.

### Standard migrations

Some standard migrations for common changes are covered with custom classes.

1) Modifying waffle switches

    Create/Delete/Rename a waffle switch can be done with a dedicated migration class.
    The class can be generated with a custom management command:

    ```bash
    ./manage.py migrate_waffle test_switch --action rename --new_name test_switch_2
    ```

    ```python
    from django.db import migrations
    import olympia.core.db.migrations


    class Migration(migrations.Migration):

        dependencies = [
        ]

        operations = [
            olympia.core.db.migrations.CreateWaffleSwitch(
                name='test_switch',
            ),
        ]
    ```

2) Back/Forward filling data (RunPython)

    Migrations that modify significant amounts of data should be run via tasks.
    You can execute the task via a migration using the custom migration class.

    The task should accept no arguments and will not be retried if it fails.
    Like all migrations, it should be idempotent and code deployed after the migration
    has run should not rely on the task having been completted successfully. Only
    rely on the task being queued.

    ```python
    from django.db import migrations
    import olympia.core.db.migrations

    class Migration(migrations.Migration):

        dependencies = [
        ]

        operations = [
            olympia.core.db.migrations.MigrationTask(
              'olympia.accounts.tasks.backfill_user_data',
            )
        ]
    ```

### Testing migrations

You can test migrations locally. This should not be considered a safe verification that a migration will work in production because the data in your local database will differ significantly from production. But this will ensure your migration runs against the same schema and with some seeded data.

- Find the current version of AMO on production.

  ```bash
  curl -s "https://addons.mozilla.org/__version__"
  ```

- Checkout the tag

  ```bash
  git checkout <tag>
  ```

- Make up initialized database

  ```bash
  make up INIT_CLEAN=True
  ```

- Checkout your branch and run the migrations

  ```bash
  git checkout <branch>
  make up
  ```

### Deploying migrations

Migrations are deployed to production automatically via the deployment pipeline.
Importantly, migrations are deployed before new code is deployed. That menas:

- If a migration fails, it will cancel the deployment.
- Migrations must be backwards compatible with the previous version of the code. see [testing migrations](#testing-migrations)

Migrations run on dedicated pods in kubernetes against the primary database. That means:

- Changes to the database schema will not be immediately reflected across all replicas immediately after the migration is deployed.
- Long running migrations could be interupted by kubernetes and should be avoided. See [writing migrations](#writing-migrations)

If you have an important data migration, consider shipping it in a dedicated release to ensure the database is migrated before required code changes are deployed. See [cherry-picking](https://mozilla.github.io/addons/server/push_duty/cherry-picking.html) for details.
