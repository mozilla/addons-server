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


----------
Stylus CSS
----------

Learn about Stylus at http://learnboost.github.com/stylus/ ::

    cd zamboni
    npm install

In your ``settings_local.py`` (or ``settings_local_mkt.py``) ensure you are
pointing to the correct executable for ``stylus``::

    STYLUS_BIN = path('node_modules/stylus/bin/stylus')

