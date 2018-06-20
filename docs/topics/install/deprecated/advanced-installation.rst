==========================
Manual installation
==========================

.. note:: The following documentation is deprecated. The approved installation is :ref:`via Docker <install-with-docker>`.

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
``memcached`` on Ubuntu and ``libmemcached`` on OS X.  Your default
settings already use the following, so you shouldn't need to change anything::

    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
            'LOCATION': ['localhost:11211'],
            'TIMEOUT': 500,
        }
    }

-------------------
RabbitMQ and Celery
-------------------

See the :doc:`./celery` page for installation instructions.  The
:ref:`example settings <example-settings>` set ``CELERY_ALWAYS_EAGER = True``.
If you're setting up Rabbit and want to use ``celery``, make sure you remove
that line from your ``local_settings.py``.


-------------
Elasticsearch
-------------

See :doc:`./elasticsearch` for more instructions.


-----
Redis
-----

On OS X the package is called ``redis``.  Get it running with the ``launchctl``
script included in homebrew.  To let olympia know about Redis, add this to
``local_settings.py``::

    CACHE_MACHINE_USE_REDIS = True
    REDIS_BACKEND = 'redis://'

The ``REDIS_BACKEND`` is parsed like ``CACHE_BACKEND`` if you need something
other than the default settings.


-------
Node.js
-------

`Node.js <http://nodejs.org/>`_ is needed for Stylus and LESS, which in turn
are needed to precompile the CSS files.

If you want to serve the CSS files from another domain than the webserver, you
will need to precompile them. Otherwise you can have them compiled on the fly,
using javascript in your browser, if you set ``LESS_PREPROCESS = False`` in
your local settings.

First, we need to install node and npm::

    brew install node
    curl https://www.npmjs.org/install.sh | sh

Optionally make the local scripts available on your path if you don't already
have this in your profile::

    export PATH="./node_modules/.bin/:${PATH}"

Not working?
 * If you're having trouble installing node, try
   http://shapeshed.com/journal/setting-up-nodejs-and-npm-on-mac-osx/.  You
   need brew, which we used earlier.
 * If you're having trouble with npm, check out the README on
   https://github.com/isaacs/npm


----------
Stylus CSS
----------

Learn about Stylus at http://learnboost.github.com/stylus/ ::

    cd olympia
    npm install

In your ``local_settings.py`` ensure you are pointing to the correct executable
for ``stylus``::

    STYLUS_BIN = path('node_modules/stylus/bin/stylus')


--------
LESS CSS
--------

We're slowing switching over from regular CSS to LESS.  You can learn more about
LESS at http://lesscss.org.

If you already ran ``npm install`` you don't need to do anything more.

In your ``local_settings.py`` ensure you are pointing to the correct executable
for ``less``::

    LESS_BIN = path('node_modules/less/bin/lessc')

You can make the CSS live refresh on save by adding ``#!watch`` to the URL or by
adding the following to your ``local_settings.py``::

    LESS_LIVE_REFRESH = True

If you want syntax highlighting, try:
 * vim: http://leafo.net/lessphp/vim/
 * emacs: http://jdhuntington.com/emacs/less-css-mode.el
 * TextMate: https://github.com/appden/less.tmbundle
 * Coda: http://groups.google.com/group/coda-users/browse_thread/thread/b3327b0cb893e439?pli=1


-----------------------------
Generating additional add-ons
-----------------------------

.. note:: If you previously used the ``make full_init`` command during
          the :doc:`./installation` process, it's not necessary to generate
          additional add-ons for initialisation/development purpose.

If you need more add-ons, you can generate additional ones using
the following command::

    python manage.py generate_addons <num_addons> [--owner <email>] [--app <application>]


where ``num_addons`` is the number of add-ons that you want to generate,
``email`` (optional) is the email address of the owner of the generated
add-ons and ``application`` (optional) the name of the application
(either ``firefox``, ``thunderbird``, ``seamonkey`` or ``android``).

By default the ``email`` will be ``nobody@mozilla.org`` and the
``application`` will be ``firefox`` if not specified.

Add-ons will have 1 preview image, 2 translations (French and
Spanish), 5 ratings and might be featured randomly.

If you didn't run the ``make full_init`` command during the
:doc:`./installation` process, categories from production
(Alerts & Updates, Appearance, and so on) will be created and randomly
populated with generated add-ons.
Otherwise, the existing categories will be filled with newly generated
add-ons.
