============================
Add-ons Server Documentation
============================

This is the documentation for the use of the addons-server and its services.
All documentation is in plain text files using
`reStructuredText <http://docutils.sourceforge.net/rst.html>`_ and
`Sphinx <http://sphinx-doc.org/>`_.

To build the documentation, you need the dependencies from
``requirements/docs.txt``.  Those are automatically installed together with
``make update_deps``, so if you've installed that already (following the
:ref:`installation` page), you're all set.

If you're unsure, activate your ``virtualenv`` and run::

    make update_deps

The documentation is viewable at http://addons-server.readthedocs.io/, and
covers development using Add-ons Server, the source code for `Add-ons
<https://addons.mozilla.org/>`_.

Its source location is in the `/docs
<https://github.com/mozilla/addons-server/tree/master/docs>`_ folder.

Note: this project was once called *olympia*, this documentation often uses
that term.

Build the documentation
-----------------------

This is as simple as running::

    make docs

This is the same as ``cd``'ing to the ``docs`` folder, and running ``make
html`` from there.

We include a daemon that can watch and regenerate the built HTML when
documentation source files change. To use it, go to the ``docs`` folder
and run::

    python watcher.py 'make html' $(find . -name '*.rst')

Once done, check the result by opening the following file in your browser:

    /path/to/olympia/docs/_build/html/index.html
