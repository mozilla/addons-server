.. _advanced-installation:

=============
Getting Fancy
=============


---------
Memcached
---------

We slipped this in with the basic install.  The package was
``libmemcached-dev`` on Ubuntu and ``libmemcached`` on OS X.  Switch your
``settings_local.py`` to use ::

    CACHE_BACKEND = 'caching.backends.memcached://localhost:11211?timeout=500'

-------------------
RabbitMQ and Celery
-------------------

See the :doc:`./celery` page for installation instructions.  The
:ref:`example settings <example-settings>` set ``CELERY_ALWAYS_EAGER = True``.
If you're setting up Rabbit and want to use ``celeryd``, make sure you remove
that line from your ``settings_local.py``.


------
Sphinx
------

On OS X the package is called ``sphinx``.  Once you have it installed, run
these two commands from the zamboni root to get it running::

    indexer -c configs/sphinx/sphinx.conf --all
    searchd -c configs/sphinx/sphinx.conf

There will probably be warnings and lots of verbose output because Sphinx sucks
like that, but it usually works.


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
