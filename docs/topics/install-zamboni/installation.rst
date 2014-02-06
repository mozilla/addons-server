.. _installation:

==================
Installing Zamboni
==================

We're going to use all the hottest tools to set up a nice environment.  Skip
steps at your own peril. Here we go!

.. note::

    For less manual work, you can build Zamboni in a
    :doc:`virtual machine using vagrant <install-with-vagrant>`
    but that has known bugs at the time of this writing.
    For best results, install manually.


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

On versions 12.04 and later, you will need to install a patched version of
M2Crypto instead of the version from PyPI. Please check the `Finish the
install`_ paragraph.


.. _osx-packages:

On OS X
~~~~~~~
The best solution for installing UNIX tools on OSX is brew_.

The following packages will get you set for zamboni::

    brew install python libxml2 mysql libmemcached openssl swig jpeg

MySQL
~~~~~

You'll probably need to :ref:`configure MySQL after install <configure-mysql>`
(especially on Mac OS X) according to advanced installation.


Use the Source
--------------

Grab zamboni from github with::

    git clone --recursive git://github.com/mozilla/zamboni.git
    cd zamboni

``zamboni.git`` is all the source code.  :ref:`updating` is detailed later on.

If at any point you realize you forgot to clone with the recursive
flag, you can fix that by running::

    git submodule update --init --recursive


virtualenv and virtualenvwrapper
--------------------------------

`virtualenv`_ is a tool to create
isolated Python environments. This will let you put all of Zamboni's
dependencies in a single directory rather than your global Python directory.
For ultimate convenience, we'll also use `virtualenvwrapper`_
which adds commands to your shell.

Are you ready to bootstrap virtualenv_ and virtualenvwrapper_?
Since each shell setup is different, you can install everything you need
and configure your shell using the `virtualenv-burrito`_. Type this::

    curl -s https://raw.github.com/brainsik/virtualenv-burrito/master/virtualenv-burrito.sh | $SHELL

Open a new shell to test it out. You should have the ``workon`` and
``mkvirtualenv`` commands.

.. _brew: http://github.com/mxcl/homebrew#readme
.. _virtualenv: http://pypi.python.org/pypi/virtualenv
.. _`virtualenv-burrito`: https://github.com/brainsik/virtualenv-burrito
.. _virtualenvwrapper: http://www.doughellmann.com/docs/virtualenvwrapper/


virtualenvwrapper Hooks (optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

virtualenvwrapper lets you run hooks when creating, activating, and deleting
virtual environments.  These hooks can change settings, the shell environment,
or anything else you want to do from a shell script.  For complete hook
documentation, see
http://www.doughellmann.com/docs/virtualenvwrapper/hooks.html.

You can find some lovely hooks to get started at http://gist.github.com/536998.
The hook files should go in ``$WORKON_HOME`` (``$HOME/Envs`` from
above), and ``premkvirtualenv`` should be made executable.


Getting Packages
----------------

Now we're ready to go, so create an environment for zamboni::

    mkvirtualenv --python=python2.6 zamboni

That creates a clean environment named zamboni using Python 2.6. You can get
out of the environment by restarting your shell or calling ``deactivate``.

To get back into the zamboni environment later, type::

    workon zamboni  # requires virtualenvwrapper

.. note:: Zamboni requires at least Python 2.6.1, production is using
          Python 2.6.6. Python 2.7 is not supported.

.. note:: If you want to use a different Python binary, pass the name (if it is
          on your path) or the full path to mkvirtualenv with ``--python``::

            mkvirtualenv --python=/usr/local/bin/python2.6 zamboni

.. note:: If you are using an older version of virtualenv that defaults to
          using system packages you might need to pass ``--no-site-packages``::

            mkvirtualenv --python=python2.6 --no-site-packages zamboni

Finish the install
~~~~~~~~~~~~~~~~~~

From inside your activated virtualenv, install the required python packages::

    pip install --no-deps -r requirements/dev.txt

If you are on a linux box and get a compilation error while installing M2Crypto
like the following::

    SWIG/_m2crypto_wrap.c:6116:1: error: unknown type name ‘STACK’

    ... snip a very long output of errors around STACK...

    SWIG/_m2crypto_wrap.c:23497:20: error: expected expression before ‘)’ token

       result = (STACK *)pkcs7_get0_signers(arg1,arg2,arg3);

                        ^

    error: command 'gcc' failed with exit status 1

It may be because of a `few reasons`_:

.. _few reasons:
    http://blog.rectalogic.com/2013/11/installing-m2crypto-in-python.html

* comment the line starting with ``M2Crypto`` in ``requirements/compiled.txt``
* install the patched package from the Debian repositories (replace
  ``x86_64-linux-gnu`` by ``i386-linux-gnu`` if you're on a 32bits platform)::

    DEB_HOST_MULTIARCH=x86_64-linux-gnu pip install -I --exists-action=w "git+git://anonscm.debian.org/collab-maint/m2crypto.git@debian/0.21.1-3#egg=M2Crypto"
    pip install --no-deps -r requirements/dev.txt

* revert your changes to ``requirements/compiled.txt``::

    git checkout requirements/compiled.txt


.. _example-settings:

Settings
--------

.. note::

    Also see the Multiple Sites section below for using settings files to run
    the Add-ons and Marketplace sites side by side.

.. note::

    There is a :doc:`settings-changelog`, this can be useful for people who are already
    setup but want to know what has recently changed.

Most of zamboni is already configured in ``settings.py``, but there's some
things you need to configure locally.  All your local settings go into
``settings_local.py``.  The settings template for
developers, included below, is at :src:`docs/settings/settings_local.dev.py`.

.. literalinclude:: /settings/settings_local.dev.py

I'm overriding the database parameters from ``settings.py`` and then extending
``INSTALLED_APPS`` and ``MIDDLEWARE_CLASSES`` to include the `Django Debug
Toolbar <http://github.com/robhudson/django-debug-toolbar>`_.  It's awesome,
you want it.

Any file that looks like ``settings_local*`` is for local use only; it will be
ignored by git.


Database
--------

Instead of running ``manage.py syncdb`` your best bet is to grab a snapshot of
our production DB which has been redacted and pruned for development use.
Development snapshots are hosted over at
https://landfill.addons.allizom.org/db/

There is a management command that download and install the landfill
database. You have to create the database first using the following
command filling in the database name from your ``settings_local.py``
(Defaults to ``zamboni``)::

    mysqladmin -uroot create $DB_NAME

Then you can just run the following command to install the landfill
database. You can also use it whenever you want to restore back to the
base landfill database::

    ./manage.py install_landfill

Here are the shell commands to pull down and set up the latest
snapshot manually (ie without the management command)::

    export DB_NAME=zamboni
    export DB_USER=zamboni
    mysqladmin -uroot create $DB_NAME
    mysql -uroot -B -e'GRANT ALL PRIVILEGES ON $DB_NAME.* TO $DB_USER@localhost'
    wget --no-check-certificate -P /tmp https://landfill.addons.allizom.org/db/landfill-`date +%Y-%m-%d`.sql.gz
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


Multiple sites
--------------

We now run multiple sites off the zamboni code base. The current sites are:

- *default* the Add-ons site at https://addons.mozilla.org/

- *mkt* the Firefox Marketplace at https://marketplace.firefox.com/

There are modules in zamboni for each of these base settings to make minor
modifications to settings, url, templates and so on. Start by copying the
template from ``docs/settings/settings_local.dev.py`` into a custom file.

To run the Add-ons site, make a ``settings_local_amo.py`` file with this import
header::

    from default.settings import *

Or to run the Marketplace site, make a ``settings_local_mkt.py`` file with
these imports::

    from mkt.settings import *


Run the Server
--------------

If you've gotten the system requirements, downloaded ``zamboni`` and
``zamboni-lib``, set up your virtualenv with the compiled packages, and
configured your settings and database, you're good to go.

To choose which site you want to run, use the `settings` command line
argument to pass in a local settings file you created above.


Run The Add-ons Server
~~~~~~~~~~~~~~~~~~~~~~

::

    ./manage.py runserver --settings=settings_local_amo 0.0.0.0:8000

.. note::

   If you don't have a LESS compiler already installed, opening
   http://localhost:8000 in your browser will raise a 500 server error.
   If you don't want to run through the :doc:`./advanced-installation`
   documentation just right now, you can disable all LESS pre-processing by
   adding the following line to your settings_local file::

      LESS_PREPROCESS = False

   Be aware, however, that this will make the site VERY slow, as a huge amount
   of LESS files will be served to your browser on EACH request, and each of
   those will be compiled on the fly by the LESS javascript compiler.


Run The Marketplace Server
~~~~~~~~~~~~~~~~~~~~~~~~~~

::

    ./manage.py runserver --settings=settings_local_mkt 0.0.0.0:8000



Persona
-------

We use `Persona <https://login.persona.org/>`_ to log in and create accounts.
In order for this to work you need to set ``SITE_URL`` and ``STATIC_URL`` in
your local settings file based on how you run your dev server. Here is an
example::

    SITE_URL = 'http://localhost:8000'
    STATIC_URL = SITE_URL + '/'  # STATIC_URL must have a trailing slash.


Create an Admin User
--------------------

To log into your dev site, you can click the login / register link and login
with Persona just like on the live site.

If, however, you don't have Persona enabled on your site, you can register a
new user "the old way" by filling in the registration form. Remember to
activate this user using the link in the confirmation email sent: it's
displayed in the console, check your server logs.

In any case, if you want to grant yourself admin privileges there are some
additional steps. After registering, find your user record::

    mysql> select * from auth_user order by date_joined desc limit 1\G

Then make yourself a superuser like this::

    mysql> update auth_user set is_superuser=1, is_staff=1 where id=<id from above>;

Additionally, add yourself to the admin group::

    mysql> insert into groups_users (group_id, user_id) values (1, <id from above>);

Next, you'll need to set a password. Do that by clicking "I forgot my password"
on the login screen then go back to the shell you started your dev server in.
You'll see the email message with the password reset link in stdout.


Setting Up the Front End
------------------------

To add the code from all front-end dependencies, you can simply run::

    commonplace fiddle

Commonplace is a set of CLI tools that will handle cloning and updating front-
end dependencies. This is done automatically if you use the ``make update_mkt``
command. More information on how this command works is available in the
`Commonplace wiki <https://github.com/mozilla/commonplace/wiki/CLI-Tools#fiddle>`_

Each of our front-end projects live in their own repositories. These are
single-page apps that talk to the APIs in Zamboni. Commonplace serves as the
glue which brings theem together and keeps them running in sync.


Testing
-------

The :ref:`testing` page has more info, but here's the quick way to run
zamboni's marketplace tests::

    ./manage.py test --settings=settings_local_mkt

Or to run AMO's tests::

    ./manage.py test --settings=settings_local_amo

There are a few useful makefile targets that you can use, the simplest one
being::

    make test

Please check the :doc:`../hacking/testing` page for more information on
the other available targets.

.. _updating:


Updating
--------

To run a full update of zamboni (including source files, pip requirements and
database migrations)::

    make update

Use the following if you also wish to prefill your database with the data from
landfill::

    make update_landfill

If you want to do it manually, then check the following steps:

This updates zamboni::

    git checkout master && git pull && git submodule update --init --recursive

This updates zamboni-lib in the ``vendor/`` directory::

    pushd vendor && git pull && git submodule update --init && popd

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
