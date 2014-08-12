.. _installation:

==================
Installing Olympia
==================

We're going to use all the hottest tools to set up a nice environment.  Skip
steps at your own peril. Here we go!

.. note::

    It was once possible to build Olympia in a
    :doc:`virtual machine using vagrant <install-with-vagrant>`
    but that has known bugs at the time of this writing.
    For best results, install manually or contribute to 956815!


Requirements
------------
To get started, you'll need:
 * Python 2.6 (greater than 2.6.1)
 * Node 0.10.x or higher
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
<apt:python-dev,python-virtualenv,libxml2-dev,libxslt1-dev,libmysqlclient-dev,libmemcached-dev,libssl-dev,swig openssl,curl>`_::

    sudo aptitude install python-dev python-virtualenv libxml2-dev libxslt1-dev libmysqlclient-dev libmemcached-dev libssl-dev swig openssl curl


.. _osx-packages:

On OS X
~~~~~~~
The best solution for installing UNIX tools on OS X is Homebrew_.

The following packages will get you set for olympia::

    brew install python libxml2 mysql libmemcached openssl swig jpeg

MySQL
~~~~~

You'll probably need to :ref:`configure MySQL after install <configure-mysql>`
(especially on Mac OS X) according to advanced installation.


Use the Source
--------------

Grab olympia from github with::

    git clone --recursive git://github.com/mozilla/olympia.git
    cd olympia

``olympia.git`` is all the source code.  :ref:`updating` is detailed later on.

If at any point you realize you forgot to clone with the recursive
flag, you can fix that by running::

    git submodule update --init --recursive


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

    mkvirtualenv --python=python2.6 olympia

That creates a clean environment named olympia using Python 2.6. You can get
out of the environment by restarting your shell or calling ``deactivate``.

To get back into the olympia environment later, type::

    workon olympia  # requires virtualenvwrapper

.. note:: Olympia requires at least Python 2.6.1, production is using
          Python 2.6.6. Python 2.7 is not supported.

.. note:: If you want to use a different Python binary, pass the name (if it is
          on your path) or the full path to mkvirtualenv with ``--python``::

            mkvirtualenv --python=/usr/local/bin/python2.6 olympia

.. note:: If you are using an older version of virtualenv that defaults to
          using system packages you might need to pass ``--no-site-packages``::

            mkvirtualenv --python=python2.6 --no-site-packages olympia

Finish the install
~~~~~~~~~~~~~~~~~~

First make sure you have a recent `pip`_ for security reasons.
From inside your activated virtualenv, install the required python packages::

    make full_update

This runs a command like this::

    pip install --no-deps -r requirements/dev.txt --exists-action=w \
                --find-links https://pyrepo.addons.mozilla.org/ \
                --allow-external PIL --allow-unverified PIL \
                --download-cache=/tmp/pip-cache

.. _pip: http://www.pip-installer.org/en/latest/


.. _example-settings:

Settings
--------

.. note::

    There is a :doc:`settings-changelog`, this can be useful for people who are already
    setup but want to know what has recently changed.

Most of olympia is already configured in ``settings.py``, but there's some
things you may want to configure locally.  All your local settings go into
``local_settings.py``.  The settings template for developers, included below,
is at :src:`docs/settings/local_settings.dev.py`.

.. literalinclude:: /settings/local_settings.dev.py

I'm extending ``INSTALLED_APPS`` and ``MIDDLEWARE_CLASSES`` to include the
`Django Debug Toolbar <http://github.com/robhudson/django-debug-toolbar>`_.
It's awesome, you want it.

The file ``local_settings.py`` is for local use only; it will be ignored by
git.


Database
--------

Instead of running ``manage.py syncdb`` your best bet is to grab a snapshot of
our production DB which has been redacted and pruned for development use.
Development snapshots are hosted over at
https://landfill-addons.allizom.org/db/

There is a management command that download and install the landfill database.
You have to create the database first using the following command filling in
the database name from your settings (Defaults to ``olympia``)::

    mysqladmin -uroot create $DB_NAME

Then you can just run the following command to install the landfill
database. You can also use it whenever you want to restore back to the
base landfill database::

    ./manage.py install_landfill

Here are the shell commands to pull down and set up the latest
snapshot manually (ie without the management command)::

    export DB_NAME=olympia
    export DB_USER=olympia
    mysqladmin -uroot create $DB_NAME
    mysql -uroot -B -e'GRANT ALL PRIVILEGES ON $DB_NAME.* TO $DB_USER@localhost'
    wget -P /tmp https://landfill-addons.allizom.org/db_data/landfill-`date +%Y-%m-%d`.sql.gz
    zcat /tmp/landfill-`date +%Y-%m-%d`.sql.gz | mysql -u$DB_USER $DB_NAME
    # Optionally, you can remove the landfill site notice:
    mysql -uroot -e"delete from config where \`key\`='site_notice'" $DB_NAME

.. note::

   If you are under Mac OS X, you might need to add a *.Z* suffix to the
   *.sql.gz* file, otherwise **zcat** might not recognize it::

      ...
      $ mv /tmp/landfill-`date +%Y-%m-%d`.sql.gz /tmp/landfill-`date +%Y-%m-%d`.sql.gz.Z
      $ zcat /tmp/landfill-`date +%Y-%m-%d`.sql.gz | mysql -u$DB_USER $DB_NAME
      ...


Database Migrations
-------------------

Each incremental change we add to the database is done with a versioned SQL
(and sometimes Python) file. To keep your local DB fresh and up to date, run
migrations like this::

    schematic migrations

More info on schematic: https://github.com/mozilla/schematic


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


Persona
-------

We use `Persona <https://login.persona.org/>`_ to log in and create accounts.
In order for this to work you need to set ``SITE_URL`` in
your local settings file based on how you run your dev server. Here is an
example::

    SITE_URL = 'http://localhost:8000'


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


Testing
-------

The :ref:`testing` page has more info, but here's the quick way to run
olympia's tests::

    ./manage.py test

There are a few useful makefile targets that you can use, the simplest one
being::

    make test

Please check the :doc:`../hacking/testing` page for more information on
the other available targets.

.. _updating:


Updating
--------

To run a full update of olympia (including source files, pip requirements and
database migrations)::

    make full_update

Use the following if you also wish to prefill your database with the data from
landfill::

    make update_landfill

If you want to do it manually, then check the following steps:

This updates olympia::

    git checkout master && git pull && git submodule update --init --recursive

This updates the python packages::

    pip install --no-deps --exists-action=w -r requirements/dev.txt

We use `schematic <http://github.com/mozilla/schematic/>`_ to run migrations::

    schematic migrations

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
