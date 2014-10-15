=====================
Olympia Documentation
=====================

This is the documentation for the use of Olympia and its services. All the
documentation here is contained in plain text files using
`reStructuredText <http://docutils.sourceforge.net/rst.html>`_ and
`Sphinx <http://sphinx-doc.org/>`_.

To build the documentation, you first need the dependencies from
``requirements/docs.txt``.  Those are automatically installed together with
``requirements/dev.txt``, so if you've installed that already (following the
:ref:`installation` page), then you're all set.

If you're unsure, activate your virtualenv and run::

    pip install --no-deps --exists-action=w --download-cache=/tmp/pip-cache -r requirements/docs.txt --find-links https://pyrepo.addons.mozilla.org/

Or simply::

    make update_deps

The documentation is viewable at http://olympia.readthedocs.org/, and covers
development using Olympia, the source code for `Add-ons
<https://addons.mozilla.org/>`_.

Its source location is in the `/docs
<https://github.com/mozilla/olympia/tree/master/docs>`_ folder.


Build the documentation
-----------------------

This is as simple as running::

    make docs

This is equivalent to ``cd``'ing to the ``docs`` folder, and running ``make
html`` from there.

A daemon is included that can watch and regenerate the built HTML when
documentation source files are changed. To use it, go to the ``docs`` folder
and run::

    python watcher.py 'make html' $(find . -name '*.rst')


Once done, check the result by opening the following file in your browser:

    /path/to/olympia/docs/_build/html/index.html
