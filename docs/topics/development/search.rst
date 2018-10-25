.. _search:

============================
How does search on AMO work?
============================

.. note::

  This is documenting our current state of how search is implemented in addons-server.
  We will be using this to plan future improvements so please note that we are
  aware that the process written below is not perfect and has bugs here and there.

  Please see https://github.com/orgs/mozilla/projects/17#card-10287357 for more planning.


General structure
=================

Our Elasticsearch cluster contains Add-ons (``addons`` index) and statistics data. The purpose of that document is to describe the add-ons part only though.

In addition to that we store the following data:

 * Add-on Versions (`Indexer / Serializer <https://github.com/mozilla/addons-server/blob/master/src/olympia/addons/indexers.py#L215-L237>`_)
 * Files for each Add-on Version
 * Compatibility information for each Add-on Version

As well as

 * Authors
 * Previews (image links)
 * Translations (`Translations mapping generation <https://github.com/mozilla/addons-server/blob/master/src/olympia/amo/indexers.py#L40-L136>`_)

And various other add-on related properties. See the `Add-on Indexer / Serializer <https://github.com/mozilla/addons-server/blob/master/src/olympia/addons/indexers.py#L215-L237>`_ for more details.

Our search can be reached either via the API through :ref:`/api/v4/addons/search/ <addon-search>` or :ref:`/api/v4/addons/autocomplete/ <addon-autocomplete>` which are used by our addons-frontend as well as via our legacy pages (used much less).

Both use similar filtering and scoring code. For legacy reasons they're not identical. We should focus on our API-based search though since the legacy search will be removed once support for Thunderbird and Seamonkey is moved to a new platform.

The legacy search uses ElasticSearch to query the data and then requests the actual model objects from the database. The newer API-based search only hits ElasticSearch and uses data directly stored from ES which is much more efficient.


Indexing
========

We index all text fields that have translations twice: once with a generic analyzer (snowball for description & summary, a custom one for name) and once with the corresponding language-specific analyzer if it exists. We also index a special variant of the name called ``name.raw`` which is a non-analyzed keyword, normalized in lowercase though a custom normalizer.

Our custom name analyzer applies the following filters: ``standard``, ``word_delimiter`` (a custom version with ``preserve_original`` set to ``true``), ``lowercase``, ``stop``, and ``dictionary_decompounder`` (with a specific word list) and ``unique``.

For each document, we store a ``boost`` field that depends on the average number of users for the add-on, as well as a multiplier for public, non-experimental add-ons.


Flow of a search query through AMO
==================================

Let's assume we search on addons-frontend (not legacy) the search query hits the API and gets handled by ``AddonSearchView``, which directly queries ElasticSearch and doesn't involve the database at all.

There are a few filters that are described in the :ref:`/api/v4/addons/search/ docs <addon-search>` but most of them are not very relevant for raw search queries. Examples are filters by guid, platform, category, add-on type or appversion (application version compatibility).

Much more relevant for raw add-on searches (and this is primarily used when you use the search on the frontend) is ``SearchQueryFilter``.

It composes various rules to define a more or less usable ranking:

Primary rules
-------------

These are the ones using the strongest boosts, so they are only applied
to a specific set of fields: add-on name and author(s) name.

**Applied rules** (merged via ``should``):

1. Prefer ``term`` matches on ``name.raw`` (``boost=100.0``) - our attempt to implement exact matches
2. Prefer phrase matches that allows swapped terms (``boost=8.0``, ``slop=1``)
3. If a query is < 20 characters long, try to do a fuzzy match on the search query (``boost=4.0``, ``prefix_length=4``, ``fuzziness=AUTO``)
4. Then text matches, using the standard text analyzer (``boost=6.0``, ``analyzer=standard``, ``operator=and``)
5. Then look for the query as a prefix (``boost=3.0``)
6. If we have a matching analyzer, add a query to ``name_l10n_{LANG}`` (``boost=5.0``, ``operator=and``)

All rules except 1 and 6 are applied to both ``name`` and ``listed_authors.name``.


Secondary rules
---------------

These are the ones using the weakest boosts, they are applied to fields
containing more text like description, summary and tags.

**Applied rules** (merged via ``should``):

1. Look for phrase matches inside the summary (``boost=2.0``)
2. Look for phrase matches inside the summary using language specific
   analyzer (``boost=3.0``)
3. Look for phrase matches inside the description (``boost=2.0``)
4. Look for phrase matches inside the description using language
   specific analyzer (``boost=3.0``)


General query flow:
-------------------

 1. Fetch current translation
 2. Fetch locale specific analyzer (`List of analyzers <https://github.com/mozilla/addons-server/blob/master/src/olympia/constants/search.py#L15-L61>`_)
 3. Merge primary and secondary *should* rules
 4. Create a ``function_score`` query that uses a ``field_value_factor`` function on ``boost`` field that we set when indexing
 5. Add a specific query-time boost for webextension add-ons
