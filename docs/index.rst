===================================
Welcome to Zamboni's documentation!
===================================

Zamboni is the codebase for https://addons.mozilla.org/ and
https://marketplace.firefox.com/ ; the source lives at https://github.com/mozilla/zamboni

If you want to build a completely different site with all the same Django
optimizations for security, scalability, L10n, and ease of use, check out
Mozilla's `Playdoh starter kit <http://playdoh.readthedocs.org/>`_.

Installation
------------
What are you waiting for?! :ref:`Install Zamboni! <installation>`


Contents
--------

.. toctree::
   :maxdepth: 2

   topics/install-zamboni/index
   topics/hacking/index

.. toctree::
   :maxdepth: 2
   :glob:

   topics/*

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
  * ``--logging-clear-handlers`` tells nose that you don't want to see any
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
