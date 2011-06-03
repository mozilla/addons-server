.. _elasticsearch:


=============
elasticsearch
=============

Installation::

    brew install elasticsearch  # or whatever your package manager is called.

Indexing::

    django cron reindex_addons

The reindex job uses celery to parallelize indexing. Running the job multiple
times will replace old index items with a new document.

The index is maintained incrementally through post_save and post_delete hooks.
