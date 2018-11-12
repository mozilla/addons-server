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

Our Elasticsearch cluster contains Add-ons (``addons`` index) and statistics data. The purpose of that document is to describe the add-ons part only though. We store two kinds of data for add-ons: indexed fields that are used for search purposes, and non-indexed fields that are meant to be returned (often as-is with no transformations) by the search API (allowing us to return search results data without hitting the database). The latter is not relevant to this document.

Our search can be reached either via the API through :ref:`/api/v4/addons/search/ <addon-search>` or :ref:`/api/v4/addons/autocomplete/ <addon-autocomplete>` which are used by our addons-frontend as well as via our legacy pages (which are going away and off-topic here).


Indexing
========

The key fields we search against are ``name``, ``summary`` and ``description``. Because all can be translated, we index twice:
- Once with the translation in the language-specific analyzer if supported, under ``{field}_l10n_{analyzer}``
- Once with the translation in the default locale of the add-on, under ``{field}``, analyzed with just the ``snowball`` analyzer for ``description`` and ``summary``, and a custom analyzer for ``name`` that applies the following filters: ``standard``, ``word_delimiter`` (a custom version with ``preserve_original`` set to ``true``), ``lowercase``, ``stop``, and ``dictionary_decompounder`` (with a specific word list) and ``unique``.

In addition, for the name, both fields also contains a subfield called ``raw`` that holds a non-analyzed variant for exact matches in the corresponding language (stored as a ``keyword``, with a ``lowercase`` normalizer).

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

1. A ``dis_max`` query with ``term`` matches on ``name_l10n_{analyzer}.raw`` and ``name.raw`` if the language of the request matches a known language-specific analyzer, or just a ``term`` query on ``name.raw`` (``boost=100.0``) otherwise - our attempt to implement exact matches
2. If we have a matching language-specific analyzer, we add a ``match`` query to ``name_l10n_{analyzer}`` (``boost=5.0``, ``operator=and``)
3. A ``phrase`` match on ``name`` that allows swapped terms (``boost=8.0``, ``slop=1``)
4. A ``match`` on ``name``, using the standard text analyzer (``boost=6.0``, ``analyzer=standard``, ``operator=and``)
5. A ``prefix`` match on ``name`` (``boost=3.0``)
6. If a query is < 20 characters long, a fuzzy match on ``name`` (``boost=4.0``, ``prefix_length=4``, ``fuzziness=AUTO``)

All rules except 1 and 2 are applied to both ``name`` and ``listed_authors.name``.


Secondary rules
---------------

These are the ones using the weakest boosts, they are applied to fields
containing more text like description, summary and tags.

**Applied rules** (merged via ``should``):

1. Look for phrase matches inside the summary (``boost=3.0``)
2. Look for phrase matches inside the description (``boost=2.0``)

If the language of the request matches a known language-specific analyzer, those are made using a ``multi_match`` query using ``summary`` or ``description`` and the corresponding ``{field}_l10n_{analyzer}``, similar to how exact name matches are performed above, in order to support potential translations.


General query flow:
-------------------

 1. Fetch current translation
 2. Fetch locale specific analyzer (`List of analyzers <https://github.com/mozilla/addons-server/blob/master/src/olympia/constants/search.py#L15-L61>`_)
 3. Merge primary and secondary *should* rules
 4. Create a ``function_score`` query that uses a ``field_value_factor`` function on ``boost`` field that we set when indexing
 5. Add a specific query-time boost for webextension add-ons
