=====================
Zamboni Documentation
=====================

Within: documentation for the use of Zamboni and its services. All this
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


Zamboni
-------

Viewable at:
  http://zamboni.readthedocs.org/
Covers:
  Development using Zamboni, the source code for
  `Add-ons <https://addons.mozilla.org/>`_ and
  `Marketplace <http://marketplace.firefox.com/>`_.
Source location:
  `/docs <https://github.com/mozilla/zamboni/tree/master/docs>`_
Build by:
  Running ``make html`` from ``/docs``. The generated documentation will be
  located at ``/docs/_build/html``.


Marketplace API
---------------

Viewable at:
  http://firefox-marketplace-api.readthedocs.org/
Covers:
  Consumption of the Marketplace API.
Source location:
  `/docs/api`` <https://github.com/mozilla/zamboni/tree/master/docs/api>`_
Build by:
  Running ``make htmlapi`` from ``/docs``. The generated documentation will be
  located at ``/docs/api/_build/html``.
