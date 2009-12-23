===================================
Welcome to zamboni's documentation!
===================================


Tip of the Day
--------------

Run your tests like this::

    python manage.py test --noinput --logging-clear-handlers

* ``--noinput`` tells Django not to ask about creating or destroying test
  databases.
* ``--loggging-clear-handlers`` tells nose that you don't want to see any
  logging output.  Without this, our debug logging will spew all over your
  console during test runs.  This can be useful for debugging, but it's not that
  great most of the time.  See the docs for more stuff you can do with
  :mod:`nose and logging <nose.plugins.logcapture>`.


Installation
------------
If you're just getting started, the :doc:`install <installation>` docs are the best.


Contents
--------

.. toctree::
   :maxdepth: 1
   :glob:

   topics/*
   ref/*
   installation


Older Tips
----------

* If you're working on the docs, use ``make loop`` to keep your built pages
  up-to-date.


Indices and tables
~~~~~~~~~~~~~~~~~~

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
