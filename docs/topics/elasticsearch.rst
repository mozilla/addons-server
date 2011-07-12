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


Settings
--------

We use a custom analyzer for indexing add-on names since they're a little
different from normal text. To get the same results as our servers, put this in
your elasticsearch.yml::

    index:
      analysis:
        analyzer:
          standardPlusWordDelimiter:
            type: custom
            tokenizer: standard
            filter: [standard, wordDelim, lowercase, stop]
        filter:
          wordDelim:
            type: word_delimiter
            preserve_original: true

If you don't do this your results will be slightly different, but you probably
wouldn't notice.
