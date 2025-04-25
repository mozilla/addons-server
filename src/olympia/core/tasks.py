from olympia.amo.celery import task
@task
def migration_task(func):
  """
  Execute a migration script function as a task.
  """
  func()
