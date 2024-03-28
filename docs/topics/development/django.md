# Django (tips and best practices)

## Types of work

There are roughly four places where business logic can be implemented. Below is a section including
when and how to use each as well as some gotchas and helpful considerations.

### Utils

Simple functions that are normally scoped to a single app. These functions might be sharable or
might just be too large to implement directly within a model or task.

### Model methods

Methods defined directly on a model to compute some data related to the particular instance. They can be used to
aggregate or transform data as well as udpate an instance according to a particular pattern at once.

### Tasks

Asynchronous functions that can be executed by our task worker celery. This is a good place for work that
can be batched, delayed or might indeterministcally error such as making network requestss.

### Cron

Work that should be executed according to a predefined schedule. Typically a cron job should execute a task or a util
method instead of implementing logic directly. This allows the underlying work to be executed "via" a cron job,
without limiting executing to such.

To create a cron job:

- add a method to an apps `cron.py` file.
- add a reference to the method and path in the `CRON_JOBS` dictionary in [settings_base.py](../../../src/olympia/lib/settings_base.py).
- add a reference to the method in the [crontab.tpl](../../../scripts/crontab/crontab.tpl) file to indicate the frequency of execution.

### Management commands

Work that should be executed manually via the console. Similarly to cron jobs a management command should likely call
another function to prevent the work from only being executable via management commands but there can be exceptions
to this.
