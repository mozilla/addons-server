===================================
Welcome to zamboni's documentation!
===================================


Tip of the Day
--------------

runserver_plus and rundevserver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Part of ``django_extensions`` is a new ``manage.py`` command:
``runserver_plus``.

This hooks in the ``Werkzeug debugger`` when there is a traceback.  This
debugger is interactive so it makes coding fun.

Similar to ``runserver_plus`` is ``rundevserver`` which does all this, and
outputs all database queries run.


Installation
------------
If you're just getting started, the :ref:`install <installation>` docs are the best.


Contents
--------

.. toctree::
   :maxdepth: 1
   :glob:

   topics/*


Older Tips
----------

gettext in Javascript
~~~~~~~~~~~~~~~~~~~~~

We have gettext in javascript!  Just mark your strings with ``gettext()`` or
``ngettext()``.  There isn't an ``_`` alias right now, since underscore.js has
that.  If we end up with a lot of js translations, we can fix that.  Check it
out::

    cd locale
    ./extract-po.py -d javascript
    pybabel init -l en_US -d . -i javascript.pot -D javascript
    perl -pi -e 's/fuzzy//' en_US/LC_MESSAGES/javascript.po
    pybabel compile -d . -D javascript
    open http://0:8000/en-US/jsi18n/

Git Bisect
~~~~~~~~~~

Did you break something recently?  Are you wondering which commit started the
problem? ::

    git bisect start
    git bisect bad
    git bisect good <master>  # Put the known-good commit here.
    git bisect run fab test
    git bisect reset

Git will churn for a while, running tests, and will eventually tell you where
you suck.  See the git-bisect man page for more details.


Running Tests
~~~~~~~~~~~~~

* Run your tests like this::

      python manage.py test --noinput --logging-clear-handlers

  * ``--noinput`` tells Django not to ask about creating or destroying test
    databases.
  * ``--loggging-clear-handlers`` tells nose that you don't want to see any
    logging output.  Without this, our debug logging will spew all over your
    console during test runs.  This can be useful for debugging, but it's not that
    great most of the time.  See the docs for more stuff you can do with
    :mod:`nose and logging <nose.plugins.logcapture>`.


Building Docs
~~~~~~~~~~~~~

* If you're working on the docs, use ``make loop`` to keep your built pages
  up-to-date.


Indices and tables
~~~~~~~~~~~~~~~~~~

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
