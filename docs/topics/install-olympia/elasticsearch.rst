.. _elasticsearch:

=============
Elasticsearch
=============

Elasticsearch is a search server. Documents (key-values) get stored,
configurable queries come in, Elasticsearch scores these documents, and returns
the most relevant hits.

Also check out `elasticsearch-head <http://mobz.github.io/elasticsearch-head/>`_,
a plugin with web front-end to elasticsearch that can be easier than talking to
elasticsearch over curl, or `Marvel <http://www.elasticsearch.org/overview/marvel/>`_,
which includes a query editors with autocompletion.

Installation
------------

Elasticsearch comes with most package managers.::

    brew install elasticsearch  # or whatever your package manager is called.

If Elasticsearch isn't packaged for your system, you can install it
manually, `here are some good instructions on how to do so
<http://www.elasticsearch.org/guide/en/elasticsearch/guide/current/_installing_elasticsearch.html>`_.

On Ubuntu, you should just download and install a .deb from the
`download page <http://www.elasticsearch.org/download/>`_.

Launching and Setting Up
------------------------

Launch the Elasticsearch service. If you used homebrew, ``brew info
elasticsearch`` will show you the commands to launch. If you used aptitude,
Elasticsearch will come with a start-stop daemon in /etc/init.d.
On Ubuntu, if you have installed from a .deb, you can type:

    sudo service elasticsearch start

Olympia has commands that sets up mappings and indexes objects such as add-ons
and apps for you. Setting up the mappings is analagous to defining the
structure of a table, indexing is analagous to storing rows.

For AMO, this will set up all indexes and start the indexing processeses::

    ./manage.py reindex

Or you could use the makefile target::

    make reindex

If you need to add arguments::

    make ARGS='--with-stats --wipe --force' reindex


Indexing
--------

Olympia has other indexing commands. It is worth noting that the index is
maintained incrementally through post_save and post_delete hooks::

    ./manage.py cron reindex_addons  # Index all the add-ons.

    ./manage.py index_stats  # Index all the update and download counts.

    ./manage.py cron reindex_collections  # Index all the collections.

    ./manage.py cron reindex_users  # Index all the users.

    ./manage.py cron compatibility_report  # Set up the compatibility index.

    ./manage.py weekly_downloads # Index weekly downloads.

Querying Elasticsearch in Django
--------------------------------

For now, we have our own query builder (which is an historical clone of
`elasticutils <http://github.com/mozilla/elasticutils>`_), but we will
switch to the official one very soon.

We attach elasticutils to Django models with a mixin. This lets us do things
like ``.search()`` which returns an object which acts a lot like Django's ORM's
object manager. ``.filter(**kwargs)`` can be run on this search object::

    query_results = list(
        MyModel.search().filter(my_field=a_str.lower())
        .values_dict('that_field'))

Testing with Elasticsearch
--------------------------

All test cases using Elasticsearch should inherit from ``amo.tests.ESTestCase``.
All such tests will be skipped by the test runner unless::

    RUN_ES_TESTS = True

This is done as a performance optimization to keep the run time of the test
suite down, unless necessary.

Troubleshooting
---------------

*I got a CircularReference error on .search()* - check that a whole object is
not being passed into the filters, but rather just a field's value.

*I indexed something into Elasticsearch, but my query returns nothing* - check
whether the query contains upper-case letters or hyphens. If so, try
lowercasing your query filter. For hyphens, set the field's mapping to not be
analyzed::

    'my_field': {'type': 'string', 'index': 'not_analyzed'}

Try running .values_dict on the query as mentioned above.
