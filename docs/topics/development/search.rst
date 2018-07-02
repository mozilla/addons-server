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

Our search contains these data types:

 * addons (`Add-ons indexer / serializer <https://github.com/mozilla/addons-server/blob/master/src/olympia/addons/indexers.py#L22-L379>`_)

  - versions (`Indexer / Serializer <https://github.com/mozilla/addons-server/blob/master/src/olympia/addons/indexers.py#L215-L237>`_)

   + files
   + compatibility information

  - authors
  - previews (image links)
  - translations (`Translations mapping generation <https://github.com/mozilla/addons-server/blob/master/src/olympia/amo/indexers.py#L40-L136>`_)
  - … various other add-on related properties

 * add-on compatibility reports

Our search can be reached either via the API through :ref:`/addons/search/ <addon-search>` or :ref:`/addons/autocomplete/ <addon-autocomplete>` which are used by our addons-frontend as well as via our legacy pages (used much less).

Both use similar filtering and scoring code. For legacy reasons they're not identical though, we should try to focus on our API-based search though since the legacy search will be removed once support for Thunderbird and Seamonkey will be moved to a new platform.

The legacy search uses ElasticSearch to query the data and then requests the actual model objects from the database. The newer API-based search only hits ElasticSearch and uses data directly stored from ES which is much more efficient.


Flow of a search query through AMO
==================================

Let's assume we search on addons-frontend (not legacy) the search query hits the API and get's handled by `AddonSearchView` which directly queries ElasticSearch and doesn't involve the database at all.

There are a few filters that are described in the :ref:`/addons/search/ docs <addon-search>` but most of them are not very relevant for raw search queries. Examplex are filters by guid, platform, category or add-on type.

Much more relevant for raw add-on searches (And this is primarily used when you use the search on the frontend) is `SearchQueryFilter`.

It composes various rules to define a more or less usable ranking:


Primary rules
  These are the ones using the strongest boosts, so they are only applied
  to a specific set of fields like the name, the slug and authors.

  Applied rules (merged via *should*):

  1. Prefer `term` matches on `name.raw` (boost=100) - our attempt to implement exact matches
  2. Prefer phrase matches that allows swapped terms (boost=4, slop=1)
  3. If a query is < 20 characters long, try to do a fuzzy match on the search query (boost=2, prefix_length=4, fuzziness=AUTO)
  4. Then text matches, using the standard text analyzer (boost=3, analyzer=standard, operator=and)
  5. Then text matches, using a language specific analyzer (boost=2.5)
  6. Then look for the query as a prefix(boost=1.5)
  7. If we have a matching analyzer, add a query to `name_l10n_{LANG}` (boost=2.5, operator=and)

  Rules 4, 5 and 6 are added for `name` and `listed_authors.name`.

Secondary rules
  These are the ones using the weakest boosts, they are applied to fields
  containing more text like description, summary and tags.

  Applied rules:

  1. Look for phrase matches inside the summary (boost=0.8)
  2. Look for phrase matches inside the summary using language specific
     analyzer (boost=0.6)
  3. Look for phrase matches inside the description (boost=0.3).
  4. Look for phrase matches inside the description using language
     specific analyzer (boost=0.6).
  5. Look for matches inside tags (boost=0.1).
  6. Append a separate 'match' query for every word to boost tag matches (boost=0.1)


General query flow:

 1. Fetch current translation
 2. Fetch locale specific analyzer (`List of analyzers <https://github.com/mozilla/addons-server/blob/master/src/olympia/constants/search.py#L15-L61>`_)
 3. Merge primary and secondary *should* rules
 4. Create a `function_score` query that uses a `field_value_factor` function on `boost`
 5. Add a specific boost for webextension related add-ons
