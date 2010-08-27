.. _celery:

======
Celery
======

`Celery <http://celeryproject.org/>`_ is a task queue powered by RabbitMQ.  You
can use it for anything that doesn't need to complete in the current
request-response cycle.  Or use it `wherever Les tells you to use it
<http://decafbad.com/blog/2008/07/04/queue-everything-and-delight-everyone>`_.

For example, each addon has a ``current_version`` cached property.  This query
on initial run causes strain on our database.  We can create a denormalized
database field called ``current_version`` on the ``addons`` table.

We'll need to populate regularly so it has fairly up-to-date data.  We can do
this in a process outside the request-response cycle.  This is where Celery
comes in.

Installation
------------

RabbitMQ
~~~~~~~~

Celery depends on RabbitMQ.  If you use ``homebrew`` you can install this:

::

  brew install rabbitmq

Setting up rabbitmq invovles some configuration.  You may want to define the
following ::

  $HOSTNAME = 'mylaptop.local'

Then run the following commands: ::

  # Set your host up so it's semi-permanent
  sudo scutil --set HostName $HOSTNAME
  cat 127.0.0.1 $HOSTNAME | sudo tee /etc/hosts

  # RabbitMQ insists on writing to /var
  sudo rabbitmq-server -detached

  # Setup rabitty things
  rabbitmqctl add_user zamboni zamboni
  rabbitmqctl add_vhost zamboni
  rabbitmqctl set_permissions -p zamboni zamboni ".*" ".*" ".*"

Back in safe and happy django-land you should be able to run: ::

  ./manage.py celeryd $OPTIONS

Celery understands python and any tasks that you have defined in your app are
now runnable asynchronously.

Celery Tasks
------------

Any python function can be set as a celery task.  For example, let's say we want
to update our ``current_version`` but we don't care how quickly it happens, just
that it happens.  We can define it like so: ::

  @task(rate_limit='2/m')
  def _update_addons_current_version(data, **kw):
      task_log.debug("[%s@%s] Updating addons current_versions." %
                     (len(data), _update_addons_current_version.rate_limit))
      for pk in data:
          try:
              addon = Addon.objects.get(pk=pk[0])
              addon.update_current_version()
          except Addon.DoesNotExist:
              task_log.debug("Missing addon: %d" % pk)

``@task`` is a decorator for Celery to find our tasks.  We can specify a
``rate_limit`` like ``2/m`` which means ``celeryd`` will only run this command
2 times a minute at most.  This keeps write-heavy tasks from killing your
database.

If we run this command like so: ::

    from celery.messaging import establish_connection

    with establish_connection() as conn:
        _update_addon_average_daily_users.apply_async(args=[pks],
                                                          connection=conn)

All the Addons with ids in ``pks`` will (eventually) have their
``current_versions`` updated.

Cron Jobs
~~~~~~~~~

This is all good, but let's automate this.  In Zamboni we can create cron
jobs like so: ::

  @cronjobs.register
  def update_addons_current_version():
      """Update the current_version field of the addons."""
      d = Addon.objects.valid().exclude(
            type=amo.ADDON_PERSONA).values_list('id')

      with establish_connection() as conn:
          for chunk in chunked(d, 1000):
              print chunk
              _update_addons_current_version.apply_async(args=[chunk],
                                                         connection=conn)

This job will hit all the addons and run the task we defined in small batches
of 1000.

We'll need to add this to both the ``prod`` and ``preview`` crontabs so that
they can be run in production.

Better than Cron
~~~~~~~~~~~~~~~~
Of course, cron is old school.  We want to do better than cron, or at least not
rely on brute force tactics.

For a surgical strike, we can call ``_update_addons_current_version`` any time
we add a new version to that addon.  Celery will execute it at the prescribed
rate, and your data will be updated ... eventually.


During Development
------------------

``celeryd`` only knows about code as it was defined at instantiation time.  If
you change your ``@task`` function, you'll need to ``HUP`` the process.

However, if you've got the ``@task`` running perfectly you can tweak all the
code, including cron jobs that call it without need of restart.
