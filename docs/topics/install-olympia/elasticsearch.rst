.. _elasticsearch:

=============
Elasticsearch
=============

Elasticsearch is a search server. Documents (key-values) get stored,
configurable queries come in, Elasticsearch scores these documents, and returns
the most relevant hits.

Also check out `elasticsearch-head <http://mobz.github.io/elasticsearch-head/>`_,
a plugin with web front-end to elasticsearch that can be easier than talking to
elasticsearch over curl.

Installation
------------

Elasticsearch comes with most package managers.::

    brew install elasticsearch  # or whatever your package manager is called.

If Elasticsearch isn't packaged for your system, you can install it
manually, `here are some good instructions on how to do so
<http://www.elasticsearch.org/tutorials/2010/07/01/setting-up-elasticsearch.html>`_.

For running Olympia you must install the
`ICU Analysis Plugin <http://www.elasticsearch.org/guide/reference/index-modules/analysis/icu-plugin/>`_.
See the `ICU Github Page <https://github.com/elasticsearch/elasticsearch-analysis-icu>`_
for instructions on installing this plugin.

On an Ubuntu box, this would mean running::

    sudo /usr/share/elasticsearch/bin/plugin -install elasticsearch/elasticsearch-analysis-icu/1.13.0

Settings
--------

.. literalinclude:: /../scripts/elasticsearch/elasticsearch.yml

We use a custom analyzer for indexing add-on names since they're a little
different from normal text.

To get the same results as our servers, configure Elasticsearch by copying the
:src:`scripts/elasticsearch/elasticsearch.yml` (available in the
``scripts/elasticsearch/`` folder of your install) to your system:

* If on OS X, copy that file into
  ``/usr/local/Cellar/elasticsearch/*/config/``.
* On Linux, the directory is ``/etc/elasticsearch/``.

.. note::

   If you are on a linux box, make sure to comment out the 4 lines relevant to
   the path configuration, unless it corresponds to an existing
   ``/usr/local/var`` folder and you want it to be stored there.

If you don't do this your results will be slightly different, but you probably
won't notice.

Launching and Setting Up
------------------------

Launch the Elasticsearch service. If you used homebrew, ``brew info
elasticsearch`` will show you the commands to launch. If you used aptitude,
Elasticsearch will come with a start-stop daemon in /etc/init.d.

Olympia has commands that sets up mappings and indexes objects such as add-ons
and apps for you. Setting up the mappings is analagous to defining the
structure of a table, indexing is analagous to storing rows.

For AMO, this will set up all indexes and start the indexing processeses::

    ./manage.py reindex --settings=your_local_amo_settings

Or you could use the makefile target (using the ``settings_local.py`` file)::

    make reindex

If you need to use another settings file and add arguments::

    make SETTINGS=settings_amo ARGS='--with-stats --wipe --force' reindex


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

We use `elasticutils <http://github.com/mozilla/elasticutils>`_, a Python
library that gives us a search API to elasticsearch.

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
