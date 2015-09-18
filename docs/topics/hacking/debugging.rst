=========
Debugging
=========

The :ref:`docker setup <install-with-docker>` uses supervisord to run the
django runserver. This means if you want to access the management server
from a shell to run things like ipdb_ you still can.

Using ipdb
----------

As with ipdb normally just add a line in your code at the relevant point:

.. code-block:: python

    import ipdb; ipdb.set_trace()

Next open a shell on the running web container (requires you to have
installed docker-utils_ first)::

    docker-utils bash web

From here you can run supervisorctl::

    supervisorctl

This will show you somthing like the following::

    bash-4.1# supervisorctl
    olympia                          RUNNING    pid 21, uptime 0:18:38
    supervisor>

To bring the runserver to the foreground type ``fg olympia`` at the
prompt::

    supervisor> fg olympia

This will bring the Django management server to the foreground and you
can interact with ipdb as you would normally.

All being well it should look like this:

.. image:: /screenshots/docker-ipdb.png


.. _ipdb: https://pypi.python.org/pypi/ipdb
.. _docker-utils: https://pypi.python.org/pypi/docker-utils
