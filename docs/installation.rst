.. _installation:

==================
Installing Zamboni
==================

We're going to use all the hottest Python tools to set up a nice environment.
Here we go!


Requirements
------------

The only we need to get started is Python 2.6.


Use the Source
~~~~~~~~~~~~~~

Grab zamboni from github with ::

    git clone git://github.com/jbalogh/zamboni.git
    git submodule update --init


virtualenv
----------

`virtualenv <http://pypi.python.org/pypi/virtualenv>`_ is a tool to create
isolated Python environments.  We're going to be installing a bunch of packages,
but we don't want your system littered with all these things you only need for
zamboni.  Some other piece of software might want an older version than zamboni
wants, which can create quite a mess.  ::

    easy_install virtualenv

virtualenv is the only package I install system-wide.  Everything else goes in a
virtual environment.


virtualenvwrapper
-----------------

`virtualenvwrapper <http://www.doughellmann.com/docs/virtualenvwrapper/>`_
complements virtualenv by installing some shell functions that make environment
management smoother.

Install it like this::

    wget http://bitbucket.org/dhellmann/virtualenvwrapper/raw/tip/virtualenvwrapper_bashrc -O ~/.virtualenvwrapper
    mkdir ~/.virtualenvs

Then put these lines in your ``~/.bashrc``::

    export WORKON_HOME=$HOME/.virtualenvs
    source $HOME/.virtualenvwrapper

``exec bash`` and you're set.

.. note:: You should really be using zsh, but you know to ``s/bash/zsh/g`` if
          you're sailing that ship.


virtualenvwrapper Hooks
~~~~~~~~~~~~~~~~~~~~~~~

virtualenvwrapper lets you run hooks when creating, activating, and deleting
virtual environments.  These hooks can change settings, the shell environment,
or anything else you want to do from a shell script.  For complete hook
documentation, see
http://www.doughellmann.com/docs/virtualenvwrapper/hooks.html.

You can find some lovely hooks to get started at http://gist.github.com/234301.
The hook files should go in ``$WORKON_HOME`` (``$HOME/.virtualenvs`` from
above), and ``premkvirtualenv`` should be made executable.


premkvirtualenv
***************

This hook installs pip and ipython into every virtualenv you create.


postactivate
************

This runs whenever you start a virtual environment.  If you have a virtual
environment named ``zamboni``, ``postactivate`` switches the shell to
``~/dev/zamboni`` if that directory exists.


Getting Packages
----------------

Now we're ready to go, so create an environment for zamboni::

    mkvirtualenv --no-site-packages zamboni

That creates a clean environment named zamboni and (for convenience) initializes
the environment.  You can get out of the environment by restarting your shell or
calling ``deactivate``.

To get back into the zamboni environment later, type::

    workon zamboni

If you keep your Python binary in a special place (i.e. you don't want to use
the system Python), pass the path to mkvirtualenv with ``--python``::

    mkvirtualenv --python=/usr/local/bin/python2.6 --no-site-packages zamboni


pip
~~~

We're going to use pip to install Python packages from `pypi
<http://pypi.python.org/pypi>`_ and github. ::

    easy_install pip

Since we're in our zamboni environment, pip was only installed locally, not
system-wide.

zamboni uses a requirements file to tell pip what to install.  Get everything
you need by running ::

    pip install -r requirements.txt

from the root of your zamboni checkout.


Settings
--------

Most of zamboni is configured in ``settings.py``, but it's incomplete since we
don't want to put database passwords into version control.  Put any local
settings into ``settings_local.py``.  Make sure you have ::

    from settings import *

in your ``settings_local.py`` so that all of the configuration is included.  If
you want to override anything, put that import at the top and then redefine
whatever parameters you want.  This is my ``settings_local.py``::

    from settings import *


    DATABASES = {
        'default': {
            'NAME': 'zamboni',
            'ENGINE': 'django.db.backends.mysql',
            'USER': 'jbalogh',
            'PASSWORD': 'foo',
            'OPTIONS':  {'init_command': 'SET storage_engine=InnoDB'},
        },
    }

    # For debug toolbar.
    MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)
    INTERNAL_IPS = ('127.0.0.1',)
    INSTALLED_APPS += ('debug_toolbar',)

    CACHE_BACKEND = 'memcached://localhost:11211'
    CACHE_DURATION = 500

    DEBUG = True

I'm overriding the database parameters from ``settings.py`` and then extending
``INSTALLED_APPS`` and ``MIDDLEWARE_CLASSES`` to include the `Django Debug
Toolbar <http://github.com/robhudson/django-debug-toolbar>`_.  It's awesome, and
I recommend you do the same.


Fin
---

Everything's good to go now (assuming you've installed a remora database clone),
so start up the development server. ::

    python manage.py runserver 0:8000
