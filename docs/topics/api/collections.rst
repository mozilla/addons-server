===========
Collections
===========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.


----
List
----

.. _collection-list:

This endpoint allows you to list all collections, filtered by an author.

.. http:get:: /api/v3/collections/collection/

    :query string author: Filter for collections authored by a particular :ref:`user <account-object>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`collections <collection-detail-object>`.


------
Detail
------

.. _collection-detail:

This endpoint allows you to fetch a single collection by its `id`.

.. http:get:: /api/v3/collections/collection/(int:collection_id)/

    .. _collection-detail-object:

    :>json int id: The id for the collection.
    :>json int addon_count: The number of add-ons in this collection.
    :>json int author.id: The id of the author (creator) of the collection.
    :>json string author.name: The name of the author.
    :>json string author.url: The link to the profile page for of the author.
    :>json string description: The description the author added to the collection.
    :>json string modified: The date the collection was last updated.
    :>json string name: The of the collection.
    :>json string url: The (absolute) collection detail URL.


-------
Add-ons
-------

.. _collection-addon:

This endpoint lists the add-ons in a collection, together with collector's notes.

.. http:get:: /api/v3/collections/collection/(int:collection_id)/addons/

    .. _collection-addon-object:

    :>json object addon: The :ref:`add-on <addon-detail-object>` for this item.
    :>json string notes: The collectors notes for this item.
    :>json int downloads: The downloads that occured via this collection.
