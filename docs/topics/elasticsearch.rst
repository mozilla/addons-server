.. _elasticsearch:


=============
elasticsearch
=============

Installation::

    brew install elasticsearch  # or whatever your package manager is called.

Indexing::

    django cron reindex_addons  # Index all the add-ons.

The reindex job uses celery to parallelize indexing. Running the job multiple
times will replace old index items with a new document.

The index is maintained incrementally through post_save and post_delete hooks.

Setting up other indexes::

    django cron reindex_collections  # Index all the collections.

    django cron reindex_users  # Index all the users.

    django cron compatibility_report  # Set up the compatibility index.

    django index_stats  # Index all the update and download counts.


Settings
--------

We use a custom analyzer for indexing add-on names since they're a little
different from normal text. To get the same results as our servers, put this in
your elasticsearch.yml (available at
:src:`scripts/elasticsearch/elasticsearch.yml`)::

.. literalinclude:: /scripts/elasticsearch/elasticsearch.yml


If you don't do this your results will be slightly different, but you probably
won't notice.
