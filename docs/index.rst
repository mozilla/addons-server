===================================
Welcome to zamboni's documentation!
===================================


Tip of the Day
--------------

Did you break something recently?  Are you wondering which commit started the
problem? ::

    git bisect start
    git bisect bad
    git bisect good <master>  # Put the known-good commit here.
    git bisect run fab test
    git bisect reset

Git will churn for a while, running tests, and will eventually tell you where
you suck.  See the git-bisect man page for more details.


Installation
------------
If you're just getting started, the :ref:`install <installation>` docs are the best.


Contents
--------

.. toctree::
   :maxdepth: 1
   :glob:

   topics/*
   ref/*


Older Tips
----------

* If you're working on the docs, use ``make loop`` to keep your built pages
  up-to-date.


* Run your tests like this::

      python manage.py test --noinput --logging-clear-handlers

  * ``--noinput`` tells Django not to ask about creating or destroying test
    databases.
  * ``--loggging-clear-handlers`` tells nose that you don't want to see any
    logging output.  Without this, our debug logging will spew all over your
    console during test runs.  This can be useful for debugging, but it's not that
    great most of the time.  See the docs for more stuff you can do with
    :mod:`nose and logging <nose.plugins.logcapture>`.


Indices and tables
~~~~~~~~~~~~~~~~~~

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
