=====================
Olympia Documentation
=====================

Within: documentation for the use of Olympia and its services. All this
documentation here is contained in plain text files using
`reStructuredText <http://docutils.sourceforge.net/rst.html>`_ and
`Sphinx <http://sphinx-doc.org/>`_.

To install Sphinx and its dependencies (including Sphinx plugins and the MDN
documentation theme), activate your virtualenv and run ``pip install -r 
requirements/docs.txt``.

A daemon is included that can watch and regenerated the built HTML when
documentation source files are changed:
``python watcher.py 'make html' $(find . -name '*.rst')``.

There are two distinct documentation trees contained within this directory:


Olympia
-------

Viewable at:
  http://olympia.readthedocs.org/
Covers:
  Development using Olympia, the source code for
  `Add-ons <https://addons.mozilla.org/>`_.
Source location:
  `/docs <https://github.com/mozilla/olympia/tree/master/docs>`_
Build by:
  Running ``make html`` from ``/docs``. The generated documentation will be
  located at ``/docs/_build/html``.
