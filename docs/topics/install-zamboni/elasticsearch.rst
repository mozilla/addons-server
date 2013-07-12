.. _elasticsearch:

=============
elasticsearch
=============

elasticsearch is a search server. Documents (key-values) get stored,
configurable queries come in, elasticsearch scores these documents, and returns
the most relevant hits.

Also check out [elasticsearch-head](http://mobz.github.io/elasticsearch-head/),
a plugin with web front-end to elasticsearch that can be easier than talking to
elasticsearch over curl.

Installation
------------

elasticsearch comes with most package managers.::

    brew install elasticsearch  # or whatever your package manager is called.

If elasticsearch isn't packaged for your system, you can install it
manually, `here are some good instructions on how to do so
<http://www.elasticsearch.org/tutorials/2010/07/01/setting-up-elasticsearch.html>`_.

Settings
--------

.. literalinclude:: /../scripts/elasticsearch/elasticsearch.yml

We use a custom analyzer for indexing add-on names since they're a little
different from normal text. To get the same results as our servers, put this in
your elasticsearch.yml (available at
:src:`scripts/elasticsearch/elasticsearch.yml`)

Once installed, we can configure elasticsearch. Zamboni has a ```config.yml```
in the ```scripts/elasticsearch/``` directory. If on OSX, copy that file into
```/usr/local/Cellar/elasticsearch/x.x.x/config/```. On Linux, the directory is
```/etc/elasticsearch/```.

If you don't do this your results will be slightly different, but you probably
won't notice.

Launching and Setting Up
------------------------

Launch the elasticsearch service. If you used homebrew, `brew info
elasticsearch` will show you the commands to launch. If you used aptitude,
elasticsearch will come with an start-stop daemon in /etc/init.d.

Zamboni has commands that sets up mappings and indexes objects such as add-ons
and apps for you. Setting up the mappings is analagous defining the structure
of a table, indexing is analagous to storing rows.::

    ./manage.py reindex --settings=your_local_mkt_settings
    ./manage.py reindex_mkt --settings=your_local_mkt_settings

Indexing
--------

Zamboni has other indexing commands. It is worth nothing the index is
maintained incrementally through post_save and post_delete hooks.::

    ./manage.py cron reindex_addons  # Index all the add-ons.

    ./manage.py cron reindex_apps # Index all the apps.

    ./manage.py index_stats  # Index all the update and download counts.

    ./manage.py index_mkt_stats  # Index contributions/installs/inapp-payments.

    ./manage.py index_stats/index_mkt_stats --addons 12345 1234 # Index
    specific addons/webapps.

    ./manage.py cron reindex_collections  # Index all the collections.

    ./manage.py cron reindex_users  # Index all the users.

    ./manage.py cron compatibility_report  # Set up the compatibility index.

    ./manage.py weekly_downloads # Index weekly downloads.

Querying ElasticSearch in Django
--------------------------------

We use [elasticutils](http://github.com/mozilla/elasticutils), a Python library
that gives us a search API to elasticsearch.

We attach elasticutils to Django models with a mixin. This lets us do things like
`.search()` which returns an object which acts a lot like Django's ORM's object
manager. `.filter(**kwargs)` can be run on this search object.::

    query_results = list(
        MyModel.search().filter(my_field=a_str.lower())
        .values_dict('that_field'))

On Marketplace, apps use ```mkt/webapps/models:WebappIndexer``` as its
interface to elasticsearch.

Testing with elasticsearch
--------------------------

All test cases using ElasticSearch should inherit from `amo.tests.ESTestCase`.
All such tests will be skipped by the test runner unless::

    RUN_ES_TESTS = True

This is done as a performance optimization to keep the run time of the test
suite down, unless necessary.

Troubleshooting
---------------

*I got a CircularReference error on .search()* - check that a whole object is
not being passed into the filters, but rather just a field's value.

*I indexed something into ElasticSearch, but my query returns nothing* - check
whether the query contains upper-case letters or hyphens. If so, try
lowercasing your query filter. For hyphens, set the field's mapping to not be
analyzed::

    'my_field': {'type': 'string', 'index': 'not_analyzed'}

Try running .values_dict on the query as mentioned above.
