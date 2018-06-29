.. _debugging:

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

Next connect to the running web container::

    make debug

This will bring the Django management server to the foreground and you
can interact with ipdb as you would normally. To quit you can just type
``Ctrl+c``.

All being well it should look like this::

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

    """)
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

Logging
-------

Logs for the celery and Django processes can be found on your machine in the
`logs` directory.

Using the Django Debug Toolbar
------------------------------

The `Django Debug Toolbar`_ is very powerful and useful when viewing pages from
the website, to check the view used, its parameters, the SQL queries, the
templates rendered and their context.

To use it please see the official getting started docs: https://django-debug-toolbar.readthedocs.io/en/1.4/installation.html#quick-setup

.. note::

    You must know that using the Django Debug Toolbar will slow the website quite a
    lot. You can mitigate this by deselecting the checkbox next to the ``SQL``
    panel.

    Also, please note that you should only use the Django Debug Toolbar if you need
    it, as it makes CSP report only for your local dev.

.. note::
    You might have to disable CSP by setting `CSP_REPORT_ONLY = True` in your
    local settings because django debug toolbar uses "data:" for its logo,
    and it uses "unsafe eval" for some panels like the templates or SQL ones.

.. _ipdb: https://pypi.python.org/pypi/ipdb
.. _Django Debug Toolbar: http://django-debug-toolbar.readthedocs.io/
