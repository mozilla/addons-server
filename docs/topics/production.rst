.. _production:

=====================
Olympia in Production
=====================


Getting Requirements
--------------------

Grab olympia from github with ::

    git clone git://github.com/mozilla/olympia.git
    git submodule update --init

You're going to need virtualenv and pip, but I'll let you figure that one out.

We rely on one compiled package, MySQLdb.  It needs to link against the
mysql-dev headers, so install that one system-wide.  The rest of our packages
should be installed in a virtualenv using pip.  If you're oremj, do this::

    pip install http://sm-hudson01.mozilla.org:8080/job/addons.mozilla.org/ws/packages/amo.pybundle

Otherwise, get them from the internet like this::

    pip install -r requirements-prod.txt


Configuration
-------------

We keep most of our config in ``settings.py`` under version control.  Local
config can be overridden in ``settings_local.py``.  This template, inlined
below,  can be found at :src:`docs/settings/settings_local.prod.py`:

.. literalinclude:: /settings/settings_local.prod.py


Setting up mod_wsgi
-------------------

https://docs.djangoproject.com/en/dev/howto/deployment/wsgi/

http://code.google.com/p/modwsgi/wiki/QuickConfigurationGuide

Here's a basic httpd.conf snippet that I used to get olympia running on my Mac
(don't forget to replace ``/Users/jeff`` with what is relevant for your install)::

    # WSGI
    LoadModule wsgi_module modules/mod_wsgi.so
    WSGIPythonHome /Users/jeff/.virtualenvs/baseline

    # TODO: /media and /admin-media

    <VirtualHost *:80>  #*
        ServerName 127.0.0.1
        WSGIScriptAlias / /Users/jeff/dev/olympia/wsgi/olympia.wsgi

        WSGIDaemonProcess olympia processes=8 threads=1 \
            python-path=/Users/jeff/.virtualenvs/olympia/lib/python2.6/site-packages
        WSGIProcessGroup olympia

        <Directory /Users/jeff/dev/olympia/wsgi>
            Order allow,deny
            Allow from all
        </Directory>
    </VirtualHost>


``WSGIPythonHome`` points at a pristine virtual environment.  That came from
http://code.google.com/p/modwsgi/wiki/VirtualEnvironments.

``WSGIScriptAlias`` points to ``/wsgi/olympia.wsgi`` in the olympia checkout.

``WSGIDaemonProcess`` creates 8 processes and 10 threads.  Those numbers are
completely arbitrary.  I'll update it when we know what works in production.
The ``python-path`` argument points to the site-packages directory of our
olympia virtualenv.

.. note:: This doesn't include media or admin media yet.
