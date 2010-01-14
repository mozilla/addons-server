.. _production:

=====================
Zamboni in Production
=====================


Getting Requirements
--------------------

Grab zamboni from github with ::

    git clone git://github.com/jbalogh/zamboni.git
    git submodule update --init

You're going to need virtualenv and pip, but I'll let you figure that one out.

We rely on one compiled package, MySQLdb.  It needs to link against the
mysql-dev headers, so install that one system-wide.  The rest of our packages
should be installed in a virtualenv using pip::

    pip install -r requirements-prod.txt


Configuration
-------------

We keep most of our config in ``settings.py`` under version control.  Local
config can be overridden in ``settings_local.py``::

    from settings import *

    DEBUG = False
    TEMPLATE_DEBUG = False

    # The default database should point to the master.
    DATABASES = {
        'default': {
            'NAME': 'zamboni',
            'ENGINE': 'django.db.backends.mysql',
            'HOST': '',
            'PORT': '',
            'USER': '',
            'PASSWORD': '',
            'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
        },
        'slave': {
            'NAME': 'zamboni',
            'ENGINE': 'django.db.backends.mysql',
            'HOST': '',
            'PORT': '',
            'USER': '',
            'PASSWORD': '',
            'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
        },
    }

    # Put the aliases for slave databases in this list.
    SLAVE_DATABASES = ['slave']

    # Use IP:PORT pairs separated by semicolons.
    CACHE_BACKEND = 'memcached://localhost:11211;localhost:11212'

    # Default time (in seconds) to cache objects.
    CACHE_DURATION = 500

    # This is used to hash some things in Django.
    SECRET_KEY = 'replace me with something long'


Setting up mod_wsgi
-------------------

http://docs.djangoproject.com/en/dev/howto/deployment/modwsgi/

http://code.google.com/p/modwsgi/wiki/QuickConfigurationGuide

Here's a basic http.conf snippet that I used to get zamboni running on my Mac::

    # WSGI
    LoadModule wsgi_module modules/mod_wsgi.so
    WSGIPythonHome /Users/jeff/.virtualenvs/baseline

    # TODO: /media and /admin-media

    <VirtualHost *:80>  #*
        ServerName 127.0.0.1
        WSGIScriptAlias / /Users/jeff/dev/zamboni/wsgi/zamboni.wsgi

        WSGIDaemonProcess zamboni processes=8 threads=10 \
            python-path=/Users/jeff/.virtualenvs/zamboni/lib/python2.6/site-packages
        WSGIProcessGroup zamboni

        <Directory /Users/jeff/dev/zamboni/wsgi>
            Order allow,deny
            Allow from all
        </Directory>
    </VirtualHost>


``WSGIPythonHome`` points at a pristine virtual environment.  That came from
http://code.google.com/p/modwsgi/wiki/VirtualEnvironments.

``WSGIScriptAlias`` points to ``/wsgi/zamboni.wsgi`` in the zamboni checkout.

``WSGIDaemonProcess`` creates 8 processes and 10 threads.  Those numbers are
completely arbitrary.  I'll update it when we know what works in production.
The ``python-path`` argument points to the site-packages directory of our
zamboni virtualenv.

.. note:: This doesn't include media or admin media yet.
