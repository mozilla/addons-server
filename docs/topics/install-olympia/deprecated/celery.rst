======
Celery
======

.. note:: The following documentation is deprecated. The approved installation is :ref:`via Docker <install-with-docker>`.

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

  # On a Mac, you can find this in System Preferences > Sharing
  export HOSTNAME='<laptop name>.local'

Then run the following commands: ::

  # Set your host up so it's semi-permanent
  sudo scutil --set HostName $HOSTNAME

  # Update your hosts by either:
  # 1) Manually editing /etc/hosts
  # 2) `echo 127.0.0.1 $HOSTNAME >> /etc/hosts`

  # RabbitMQ insists on writing to /var
  sudo rabbitmq-server -detached

  # Setup rabitty things (sudo is required to read the cookie file)
  sudo rabbitmqctl add_user olympia olympia
  sudo rabbitmqctl add_vhost olympia
  sudo rabbitmqctl set_permissions -p olympia olympia ".*" ".*" ".*"

Back in safe and happy django-land you should be able to run: ::

  celery -A olympia worker -E

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
              addon = Addon.objects.get(pk=pk)
              addon.update_version()
          except Addon.DoesNotExist:
              task_log.debug("Missing addon: %d" % pk)

``@task`` is a decorator for Celery to find our tasks.  We can specify a
``rate_limit`` like ``2/m`` which means ``celery`` will only run this command
2 times a minute at most.  This keeps write-heavy tasks from killing your
database.

If we run this command like so: ::

    from celery.task.sets import TaskSet

    all_pks = Addon.objects.all().values_list('pk', flat=True)
    ts = [_update_addons_current_version.subtask(args=[pks])
          for pks in amo.utils.chunked(all_pks, 300)]
    TaskSet(ts).apply_async()

All the Addons with ids in ``pks`` will (eventually) have their
``current_versions`` updated.

Cron Jobs
~~~~~~~~~

This is all good, but let's automate this. In Olympia we can create cron
jobs like so: ::

  @cronjobs.register
  def update_addons_current_version():
      """Update the current_version field of the addons."""
      d = Addon.objects.valid().exclude(
            type=amo.ADDON_PERSONA).values_list('id', flat=True)

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

``celery`` only knows about code as it was defined at instantiation time.  If
you change your ``@task`` function, you'll need to ``HUP`` the process.

However, if you've got the ``@task`` running perfectly you can tweak all the
code, including cron jobs that call it without need of restart.
