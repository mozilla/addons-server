.. _installation:

===============================
Installing Olympia the long way
===============================

.. note:: The following documentation is deprecated. The approved installation is :ref:`via Docker <install-with-docker>`.


The following instructions walk you through installing and configuring all
required services from scratch.

We're going to use all the hottest tools to set up a nice environment.  Skip
steps at your own peril. Here we go!


Requirements
------------
To get started, you'll need:
 * Python 2.7 (2.7 -> 2.7.10)
 * Node 0.10.x or higher
 * MySQL
 * ElasticSearch
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
<apt:python-dev,python-virtualenv,libxml2-dev,libxslt1-dev,libmysqlclient-dev,memcached,libssl-dev,swig openssl,curl,libjpeg-dev,zlib1g-dev,libsasl2-dev>`_::

    sudo apt-get install python-dev python-virtualenv libxml2-dev libxslt1-dev libmysqlclient-dev memcached libssl-dev swig openssl curl libjpeg-dev zlib1g-dev libsasl2-dev nodejs nodejs-legacy

.. note:: As of writing, M2Crypto is only compatible with swig <=3.0.4 version's. So, if you encounter a libssl exception while running
          ``make full_init``, you might have to downgrade swig to version <=3.0.4.

.. _osx-packages:

On OS X
~~~~~~~
The best solution for installing UNIX tools on OS X is Homebrew_.

The following packages will get you set for olympia::

    brew install python libxml2 mysql libmemcached openssl swig jpeg

.. note:: As of writing, M2Crypto is only compatible with swig <=3.0.4 version's. So, if you encounter a libssl exception while running
          ``make full_init``, you might have to downgrade swig to version <=3.0.4.


MySQL
~~~~~

You'll probably need to :ref:`configure MySQL after install <configure-mysql>`
(especially on Mac OS X) according to advanced installation.

See :ref:`installation-database` for creating and managing the database.


Elasticsearch
~~~~~~~~~~~~~

You'll need an Elasticsearch server up and running during the init script. See :doc:`./elasticsearch` for more instructions.


Use the Source
--------------

Grab olympia from github with::

    git clone git://github.com/mozilla/olympia.git
    cd olympia

``olympia.git`` is all the source code.  :ref:`updating` is detailed later on.


virtualenv and virtualenvwrapper
--------------------------------

`virtualenv`_ is a tool to create
isolated Python environments. This will let you put all of Olympia's
dependencies in a single directory rather than your global Python directory.
For ultimate convenience, we'll also use `virtualenvwrapper`_
which adds commands to your shell.

Are you ready to bootstrap virtualenv_ and virtualenvwrapper_?
Since each shell setup is different, you can install everything you need
and configure your shell using the `virtualenv-burrito`_. Type this::

    curl -sL https://raw.github.com/brainsik/virtualenv-burrito/master/virtualenv-burrito.sh | $SHELL

Open a new shell to test it out. You should have the ``workon`` and
``mkvirtualenv`` commands.

.. _Homebrew: http://brew.sh/
.. _virtualenv: http://pypi.python.org/pypi/virtualenv
.. _`virtualenv-burrito`: https://github.com/brainsik/virtualenv-burrito
.. _virtualenvwrapper: http://www.doughellmann.com/docs/virtualenvwrapper/


virtualenvwrapper Hooks (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

virtualenvwrapper lets you run hooks when creating, activating, and deleting
virtual environments. These hooks can change settings, the shell environment,
or anything else you want to do from a shell script. For complete hook
documentation, see
http://www.doughellmann.com/docs/virtualenvwrapper/hooks.html.

You can find some lovely hooks to get started at http://gist.github.com/536998.
The hook files should go in ``$WORKON_HOME`` (``$HOME/Envs`` from
above), and ``premkvirtualenv`` should be made executable.


Getting Packages
----------------

Now we're ready to go, so create an environment for olympia::

    mkvirtualenv olympia

That creates a clean environment named olympia using your default python. You
can get out of the environment by restarting your shell or calling
``deactivate``.

To get back into the olympia environment later, type::

    workon olympia  # requires virtualenvwrapper

.. note:: Olympia requires Python 2.7.

.. note:: If you want to use a different Python binary, pass the name (if it is
          on your path) or the full path to mkvirtualenv with ``--python``::

            mkvirtualenv --python=/usr/local/bin/python2.7 olympia


Finish the install
~~~~~~~~~~~~~~~~~~

First make sure you have a recent `pip`_ for security reasons::

    pip install --upgrade pip

From inside your activated virtualenv, install the required python packages,
initialize the database, create a super user, compress the assets, ...::

    make full_init

.. _pip: http://www.pip-installer.org/en/latest/


.. _example-settings:

Settings
--------

Most of olympia is already configured in ``settings.py``, but there's some
things you may want to configure locally.  All your local settings go into
``local_settings.py``.  The settings template for developers, included below,
is at :src:`docs/settings/local_settings.dev.py`.

.. literalinclude:: /settings/local_settings.dev.py

I'm extending ``INSTALLED_APPS`` and ``MIDDLEWARE_CLASSES`` to include the
`Django Debug Toolbar <https://github.com/django-debug-toolbar/django-debug-toolbar>`_.
It's awesome, you want it.

The file ``local_settings.py`` is for local use only; it will be ignored by
git.

.. _installation-database:

Database
--------

By default, Olympia connects to the ``olympia`` database running on
``localhost`` as the user ``root``, with no password. To create a database,
run::

    $ mysql -u root -p
    mysql> CREATE DATABASE olympia CHARACTER SET utf8 COLLATE utf8_unicode_ci;


If you want to change settings, you can either add the database settings in
your :ref:`local_settings.py<example-settings>` or set the environment variable
``DATABASE_URL``::

    export DATABASES_DEFAULT_URL=mysql://<user>:<password>@<hostname>/<database>

If you've changed the user and password information, you need to grant
permissions to the new user::

    $ mysql -u root -p
    mysql> GRANT ALL ON olympia.* TO <YOUR_USER>@localhost IDENTIFIED BY '<YOUR_PASSWORD>';

Finally, to run the test suite, you'll need to add an extra grant in MySQL for
your database user::

    $ mysql -u root -p
    mysql> GRANT ALL ON test_olympia.* TO <YOUR_USER>@localhost IDENTIFIED BY '<YOUR_PASSWORD>';

.. warning::

   Don't forget to change ``<YOUR_USER>`` and ``<YOUR_PASSWORD>`` to your
   actual database credentials.

The database is initialized automatically using the ``make full_init`` command
you saw earlier.


Database Migrations
-------------------

Each incremental change we add to the database is done with a versioned SQL
(and sometimes Python) file. To keep your local DB fresh and up to date, run
migrations like this::

    $ schematic migrations/

If, at some point, you want to start from scratch and recreate the database,
you can just run the ``make initialize_db`` command. This will also fake all
the `schematic`_ migrations, and allow you to create a superuser.

.. _schematic: https://github.com/mozilla/schematic

Run the Server
--------------

If you've gotten the system requirements, downloaded ``olympia``, set up your
virtualenv with the compiled packages, and configured your settings and
database, you're good to go.

::

    ./manage.py runserver

.. note::

   If you don't have a LESS compiler already installed, opening
   http://localhost:8000 in your browser will raise a 500 server error.
   If you don't want to run through the :doc:`./advanced-installation`
   documentation just right now, you can disable all LESS pre-processing by
   adding the following line to your ``local_settings.py`` file::

      LESS_PREPROCESS = False

   Be aware, however, that this will make the site VERY slow, as a huge amount
   of LESS files will be served to your browser on EACH request, and each of
   those will be compiled on the fly by the LESS javascript compiler.


Create an Admin User
--------------------

To connect to the site, you first need to register a new user "the standard
way" by filling in the registration form.

Once this is done, you can either activate this user using the link in the
confirmation email sent (it's displayed in the console, check your server
logs), or use the following handy management command::

    ./manage.py activate_user <email of your user>

If you want to grant yourself admin privileges, pass in the ``--set-admin``
option::

    ./manage.py activate_user --set-admin <email of your user>

.. _updating:


Updating
--------

To run a full update of olympia (including source files, pip requirements and
database migrations)::

    make full_update

If you want to do it manually, then check the Makefile.

The :ref:`contributing` page has more on managing branches.


Contact
-------

Come talk to us on irc://irc.mozilla.org/amo if you have questions, issues, or
compliments.


Submitting a Patch
------------------

See the :ref:`contributing` page.


.. _advanced-install:

Advanced Installation
---------------------

In production we use things like memcached, rabbitmq + celery,
elasticsearch, LESS, and Stylus.  Learn more about installing these on the
:doc:`./advanced-installation` page.

.. note::

    Although we make an effort to keep advanced items as optional installs
    you might need to install some components in order to run tests or start
    up the development server.
