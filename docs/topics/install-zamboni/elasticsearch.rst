.. _elasticsearch:


=============
elasticsearch
=============
elasticsearch is a (magical black-box beast) search server that is used like a
key-value store.

Installation::

    brew install elasticsearch  # or whatever your package manager is called.

If elasticsearch isn't packaged for your system, you will have to install it
manually, `here are some good instructions on how to do so
<http://www.elasticsearch.org/tutorials/2010/07/01/setting-up-elasticsearch.html>`_.

Launch elasticsearch. If you used homebrew, `brew info elasticsearch`
will show you the commands to launch. If you used aptitude, elasticsearch will
come with an start-stop daemon in /etc/init.d as well as configuration files in
/etc/elasticsearch.

There is a ```config.yml``` in the ```scripts/elasticsearch/```
directory. If you installed via brew, copy that file into
```/usr/local/Cellar/elasticsearch/x.x.x/config/```. On Linux, the
configuration directory is often ```/etc/elasticsearch/```.

Mappings::

    ./manage.py shell_plus
    from stats.search import setup_indexes
    setup_indexes()

    ./manage.py shell_plus --settings=your_local_mkt_settings
    from mkt.stats.search import setup_mkt_indexes
    setup_mkt_indexes()

Setting up the mappings is similar to defining the schema for a database or
structure of a table. For different tables, we define different mappings that
explicitly define fields to store and their type. We can also define what
analyzer or tokenizer ElasticSearch uses on those fields. If a field is not
explicitly defined, ElasticSearch dynamically guesses the field's type in a
schemaless manner.

Indexing::

    ./manage.py cron reindex_addons  # Index all the add-ons.

The reindex job uses celery to parallelize indexing. Running the job multiple
times will replace old index items with a new document. You will want to set up
the mappings, and run the indexing for a bit upon starting.

The index is maintained incrementally through post_save and post_delete hooks.

Setting up other indexes::

    ./manage.py index_stats  # Index all the update and download counts.

    ./manage.py index_mkt_stats  # Index contributions/installs/inapp-payments.

    ./manage.py index_stats/index_mkt_stats --addons 12345 1234 # Index
    specific addons/webapps.

    ./manage.py cron reindex_collections  # Index all the collections.

    ./manage.py cron reindex_users  # Index all the users.

    ./manage.py cron compatibility_report  # Set up the compatibility index.

    ./manage.py weekly_downloads # Index weekly downloads.


Settings
--------

We use a custom analyzer for indexing add-on names since they're a little
different from normal text. To get the same results as our servers, put this in
your elasticsearch.yml (available at
:src:`scripts/elasticsearch/elasticsearch.yml`)

.. literalinclude:: /../scripts/elasticsearch/elasticsearch.yml

If you installed ElasticSearch via apt-get/aptitude, place this configuration
file in `/etc/elasticsearch/` and restart ElasticSearch with
`/etc/init.d/elasticsearch restart`.

If you don't do this your results will be slightly different, but you probably
won't notice.


Querying ElasticSearch in Django
--------------------------------
Django models in zamboni are instantiated with a SearchMixin that has
functions that communicate with ElasticSearch through elasticutils. A notable
one is `.search()` which returns an ElasticSearch search object which acts a
lot like Django's ORM's object manager. `.filter(**kwargs)` can be run on this
search object. Sometimes a query returns nothing unless `.values_dict` is
called on the query set::

    query_results = list(MyModel.search().filter(
    a_field=a_str.lower()).values_dict('that_field'))


Testing with elasticsearch
--------------------------

All test cases using ElasticSearch should inherit from `amo.tests.ESTestCase`. All such tests will be skipped by the test runner unless::

    RUN_ES_TESTS = True

This is done as a performance optimization to keep the run time of the test suite down, unless necessary.


Common Pitfalls
---------------

*I got a CircularReference error on .search()* - check that a whole object is
not being passed into the filters, but rather just a field's value

*I indexed something into ElasticSearch, but my query returns nothing* - check
whether the query contains upper-case letters or hyphens. If so, try
lowercasing your query filter. For hyphens, set the field's mapping to not be
analyzed::

    'my_field': {'type': 'string', 'index': 'not_analyzed'}

Also try running .values_dict on the query as mentioned above
