.. _advanced-installation:

=============
Getting Fancy
=============

.. _configure-mysql:

-----
MySQL
-----

On your dev machine, MySQL probably needs some tweaks. Locate your my.cnf (or
create one) then, at the very least, make UTF8 the default encoding::

    [mysqld]
    character-set-server=utf8

Here are some other helpful settings::

    [mysqld]
    default-storage-engine=innodb
    character-set-server=utf8
    skip-sync-frm=OFF
    innodb_file_per_table

On Mac OS X with homebrew, put my.cnf in ``/usr/local/Cellar/mysql/5.5.15/my.cnf`` then restart like::

    launchctl unload -w ~/Library/LaunchAgents/com.mysql.mysqld.plist
    launchctl load -w ~/Library/LaunchAgents/com.mysql.mysqld.plist

.. note:: some of the options above were renamed between MySQL versions

Here are `more tips for optimizing MySQL <http://bonesmoses.org/2011/02/28/mysql-isnt-yoursql/>`_ on your dev machine.

---------
Memcached
---------

We slipped this in with the basic install.  The package was
``libmemcached-dev`` on Ubuntu and ``libmemcached`` on OS X.  Switch your
``settings_local.py`` to use ::

    CACHES = {
        'default': {
            'BACKEND': 'caching.backends.memcached.CacheClass',
            'LOCATION': ['localhost:11211'],
            'TIMEOUT': 500,
        }
    }

-------------------
RabbitMQ and Celery
-------------------

See the :doc:`./celery` page for installation instructions.  The
:ref:`example settings <example-settings>` set ``CELERY_ALWAYS_EAGER = True``.
If you're setting up Rabbit and want to use ``celeryd``, make sure you remove
that line from your ``settings_local.py``.


-------------
elasticsearch
-------------

See :doc:`./elasticsearch` for more instructions.


-----
Redis
-----

On OS X the package is called ``redis``.  Get it running with the ``launchctl``
script included in homebrew.  To let zamboni know about Redis, add this to
``settings_local.py``::

    CACHE_MACHINE_USE_REDIS = True
    REDIS_BACKEND = 'redis://'

The ``REDIS_BACKEND`` is parsed like ``CACHE_BACKEND`` if you need something
other than the default settings.


--------
LESS CSS
--------

We're slowing switching over from regular CSS to LESS.  You can learn more about
LESS at http://lesscss.org.

If you are serving your CSS from the same domain as the page, you don't
need to do anything.  Otherwise, see "Installing LESS (alternative)" below.

You can make the CSS live refresh on save by adding ``#!watch`` to the URL or by
adding the following to your ``settings_local.py``::

    LESS_LIVE_REFRESH = True

If you want syntax highlighting, try:
 * vim: http://leafo.net/lessphp/vim/
 * emacs: http://jdhuntington.com/emacs/less-css-mode.el
 * TextMate: https://github.com/appden/less.tmbundle
 * Coda: http://groups.google.com/group/coda-users/browse_thread/thread/b3327b0cb893e439?pli=1


Installing LESS (alternative)
*****************************

You only need to do this if your CSS is being served from a separate domain, or
if you're using zamboni in production and running the build scripts.

If you aren't serving your CSS from the same domain as zamboni, you'll need
to install node so that we can compile it on the fly.

First, we need to install node, npm and LESS::

    brew install node
    curl http://npmjs.org/install.sh | sh

Install all of zamboni's dependencies locally::

    cd zamboni
    npm install

Make the local scripts available on your path if you don't already have this in
your profile::

    export PATH="./node_modules/.bin/:${PATH}"

If you type ``lessc``, it should say "lessc: no input files."

Next, add this to your settings_local.py::

    LESS_PREPROCESS = True
    LESS_BIN = 'lessc'

Make sure ``LESS_BIN`` is correct.

Not working?
 * If you're having trouble installing node, try http://shapeshed.com/journal/setting-up-nodejs-and-npm-on-mac-osx/.  You need brew, which we used earlier.
 * If you're having trouble with npm, check out the README on https://github.com/isaacs/npm
 * If you can't run LESS after installing, make sure it's in your PATH.  You should be
   able to type "lessc", and have "lessc: no input files" returned.

