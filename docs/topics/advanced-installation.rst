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
    npm install less

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

