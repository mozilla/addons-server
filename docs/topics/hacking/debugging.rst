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

Next open a shell on the running web container::

    docker exec -t -i olympia_web_1 supervisorctl fg olympia

This will bring the Django management server to the foreground and you
can interact with ipdb as you would normally. To quit you can just type
``Ctrl+c``.

All being well it should look like this:

.. image:: /screenshots/docker-ipdb.png

If you would rather use docker-utils_ you can do the following::

    docker-utils bash web

From here you can run supervisorctl::

    supervisorctl

This will show you something like the following::

    bash-4.1# supervisorctl
    olympia                          RUNNING    pid 21, uptime 0:18:38
    supervisor>

To bring the runserver to the foreground type ``fg olympia`` at the
prompt::

    supervisor> fg olympia

To quit you can just type ``Ctrl+c`` (this will bring you back to the
supervisorctl prompt). There you can type ``exit`` to quit (sometimes exiting
the supervisorctl prompt doesn't respond so closing that shell is another
option).



Using the Django Debug Toolbar
------------------------------

The `Django Debug Toolbar`_ is very powerful and useful when viewing pages from
the website, to check the view used, its parameters, the SQL queries, the
templates rendered and their context...

To enable it add the following setting to your ``local_settings.py`` file (you
may need to create it)::

    DEBUG_TOOLBAR_CONFIG = {
        "SHOW_TOOLBAR_CALLBACK": "settings.debug_toolbar_enabled",
    }

All being well it should look like this at the top-right of any web page on
olympia:

.. image:: /screenshots/django-debug-toolbar.png

If clicked, it looks like:

.. image:: /screenshots/django-debug-toolbar-expanded.png

.. _ipdb: https://pypi.python.org/pypi/ipdb
.. _docker-utils: https://pypi.python.org/pypi/docker-utils
.. _Django Debug Toolbar: http://django-debug-toolbar.readthedocs.org/en/1.3.2/index.html
