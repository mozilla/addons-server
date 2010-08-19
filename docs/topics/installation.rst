.. _installation:

==================
Installing Zamboni
==================

We're going to use all the hottest tools to set up a nice environment.  Skip
steps at your own peril. Here we go!


Requirements
------------
To get started, you'll need:
 * Python 2.6
 * MySQL
 * libxml2 (for building lxml, used in tests)

:ref:`OS X <osx-packages>` and :ref:`Ubuntu <ubuntu-packages>` instructions
follow.

There are a lot of advanced dependencies we're going to skip for a fast start.
They have their own :ref:`section <advanced-install>`.

If you're on a Linux distro that splits all its packages into ``-dev`` and
normal stuff, make sure you're getting all those ``-dev`` packages.


.. _ubuntu-packages:

On Ubuntu
~~~~~~~~~
The following command will install the required development files on Ubuntu or,
if you're running a recent version, you can `install them automatically
<apt:python-dev,python-virtualenv,libxml2-dev,libxslt1-dev,libmysqlclient-dev,libmemcached-dev>`_::

    sudo aptitude install python-dev python-virtualenv libxml2-dev libxslt1-dev libmysqlclient-dev libmemcached-dev


.. _osx-packages:

On OS X
~~~~~~~
The best solution for installing UNIX tools on OSX is Homebrew_.

The following packages will get you set for zamboni::

    brew install python libxml2 mysql libmemcached

.. _Homebrew: http://github.com/mxcl/homebrew#readme


Use the Source
--------------

Grab zamboni from github with::

    git clone --recursive git://github.com/jbalogh/zamboni.git
    cd zamboni
    git clone --recursive git://github.com/jbalogh/zamboni-lib.git vendor

``zamboni.git`` is all the source code.  ``zamboni-lib.git`` is all of our
pure-Python dependencies.  :ref:`updating` is detailed later on.


virtualenv
----------

`virtualenv <http://pypi.python.org/pypi/virtualenv>`_ is a tool to create
isolated Python environments.  We don't want to install packages system-wide
because that can create quite a mess. ::

    sudo easy_install virtualenv

virtualenv is the only Python package I install system-wide.  Everything else
goes in a virtual environment.


virtualenvwrapper
~~~~~~~~~~~~~~~~~

`virtualenvwrapper <http://www.doughellmann.com/docs/virtualenvwrapper/>`_
is a set of shell functions that make virtualenv easy to work with.

Install it like this::

    wget http://bitbucket.org/dhellmann/virtualenvwrapper/raw/f31869779141/virtualenvwrapper_bashrc -O ~/.virtualenvwrapper
    mkdir ~/.virtualenvs

Then put these lines in your ``~/.bashrc``::

    export WORKON_HOME=$HOME/.virtualenvs
    source $HOME/.virtualenvwrapper

``exec bash`` and you're set.

.. note:: If you didn't have a ``.bashrc`` already, you should make a
          ``~/.profile`` too::

            echo 'source $HOME/.bashrc' >> ~/.profile


virtualenvwrapper Hooks (optional)
**********************************

virtualenvwrapper lets you run hooks when creating, activating, and deleting
virtual environments.  These hooks can change settings, the shell environment,
or anything else you want to do from a shell script.  For complete hook
documentation, see
http://www.doughellmann.com/docs/virtualenvwrapper/hooks.html.

You can find some lovely hooks to get started at http://gist.github.com/536998.
The hook files should go in ``$WORKON_HOME`` (``$HOME/.virtualenvs`` from
above), and ``premkvirtualenv`` should be made executable.


Getting Packages
----------------

Now we're ready to go, so create an environment for zamboni::

    mkvirtualenv --no-site-packages zamboni

That creates a clean environment named zamboni.  You can get out of the
environment by restarting your shell or calling ``deactivate``.

To get back into the zamboni environment later, type::

    workon zamboni  # requires virtualenvwrapper

.. note:: If you want to use a different Python binary, pass the path to
          mkvirtualenv with ``--python``::

            mkvirtualenv --python=/usr/local/bin/python2.6 --no-site-packages zamboni


Finish the install
~~~~~~~~~~~~~~~~~~

From inside your activated virtualenv, run::

    pip install -r requirements/compiled.txt

pip installs a few packages into our new virtualenv that we can't distribute in
``zamboni-lib``.  These require a C compiler.


.. _example-settings:

Settings
--------

Most of zamboni is already configured in ``settings.py``, but there's some
things you need to configure locally.  All your local settings go into
``settings_local.py``. Make sure you have ::

    from settings import *

at the top of your ``settings_local.py``.  The settings template for
developers, included below, is at :src:`docs/settings/settings_local.dev.py`.

.. literalinclude:: /settings/settings_local.dev.py

I'm overriding the database parameters from ``settings.py`` and then extending
``INSTALLED_APPS`` and ``MIDDLEWARE_CLASSES`` to include the `Django Debug
Toolbar <http://github.com/robhudson/django-debug-toolbar>`_.  It's awesome,
you want it.


Database
--------

If you have access, ask us how to get a copy of the production database.  We're
still working out how to get useful data for outside contributors.

Let Django sync up the database schema for you::

    ./manage.py syncdb --noinput


Run the Server
--------------

If you've gotten the system requirements, downloaded ``zamboni`` and
``zamboni-lib``, set up your virtualenv with the compiled packages, and
configured your settings and database, you're good to go.  Run the server::

    ./manage.py runserver 0.0.0.0:8000


Contact
-------

Come talk to us on irc://irc.mozilla.org/amo if you have questions, issues, or
compliments.


Testing
-------

The :ref:`testing` page has more info, but here's the quick way to run
zamboni's tests::

    ./manage.py test


.. _updating:

Updating
--------

This updates zamboni::

    git checkout master && git pull && git submodule update --init

This updates zamboni-lib in the ``vendor/`` directory::

    pushd vendor && git pull && git submodule update --init && popd

We use `schematic <http://github.com/jbalogh/schematic/>`_ to run migrations::

    ./vendor/src/schematic/schematic migrations

The :doc:`./contributing` page has more on managing branches.


Submitting a Patch
------------------

See the :doc:`./contributing` page.


.. _advanced-install:

Advanced Installation
---------------------

In production we use things like memcached, rabbitmq + celery, sphinx, redis,
and mongodb.  Learn more about installing these on the
:doc:`./advanced-installation` page.
