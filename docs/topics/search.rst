.. _sphinx_search:

================================
Search (powered by SphinxSearch)
================================

Search is powered by `Sphinx <http://sphinxsearch.com>`_.  It allows us to do
very fast full-text search and avoid hitting the mysql databases or polluting
them with search-related data.

Production
----------

Production at peak load based on log analysis done in 2009 suggests that we
serve 10q/s.

Sphinx is served from two load balanced nodes that also serve sphinx for
preview and SUMO.

Testing
-------

Testing of Sphinx can be remarkably slower since Sphinx needs to populate
tables and truncate tables for each test.  If you are trying to run a quick
test you can always omit Sphinx::

    ./manage.py test -a\!sphinx

Addon criteria for being indexed
--------------------------------

Sphinx tries to index all valid addons.  The query in
`configs/sphinx/sphinx.conf` looks for addons that meet the following criteria:

* A name needs to be set for the default locale.  E.g. if your default locale
  is ``fr`` there should be a corresponding translation for the name in ``fr``.
* Only (non default) translations of an addon that have either a description or
  summary set will be indexed.  E.g. if your addon has ``en-US`` as a default
  locale, the ``fr`` locale won't be indexed if you haven't set a description
  or a summary.
