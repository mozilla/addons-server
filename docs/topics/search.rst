.. _search :

==================================================
Search (powered by Sphinx, but not the documenter)
==================================================

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

