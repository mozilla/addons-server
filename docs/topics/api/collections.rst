===========
Collections
===========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

The following API endpoints cover user created collections.


----
List
----

.. _collection-list:

.. note::
    This API requires :doc:`authentication <auth>`.

This endpoint allows you to list all collections authored by the specified user.
The results are sorted by the most recently updated collection first.


.. http:get:: /api/v4/accounts/account/(int:user_id|string:username)/collections/

    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`collections <collection-detail-object>`.


------
Detail
------

.. _collection-detail:

This endpoint allows you to fetch a single collection by its ``slug``.
It returns any ``public`` collection by the specified user. You can access
a non-``public`` collection only if it was authored by you, the authenticated user.
If you have ``Admin:Curation`` permission you can see any collection belonging
to the ``mozilla`` user.


.. http:get:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/

    .. _collection-detail-object:

    :>json int id: The id for the collection.
    :>json int addon_count: The number of add-ons in this collection.
    :>json int author.id: The id of the author (creator) of the collection.
    :>json string author.name: The name of the author.
    :>json string author.url: The link to the profile page for of the author.
    :>json string author.username: The username of the author.
    :>json string default_locale: The default locale of the description and name fields. (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null description: The description the author added to the collection. (See :ref:`translated fields <api-overview-translations>`).
    :>json string modified: The date the collection was last updated.
    :>json string|object name: The name of the collection. (See :ref:`translated fields <api-overview-translations>`).
    :>json boolean public: Whether the collection is `listed` - publicly viewable.
    :>json string slug: The name used in the URL.
    :>json string url: The (absolute) collection detail URL.
    :>json string uuid: A unique identifier for this collection; primarily used to count addon installations that come via this collection.


If the ``with_addons`` parameter is passed then :ref:`addons in the collection<collection-addon-detail>` are returned along with the detail.
Add-ons returned are limited to the first 25 in the collection, in the default sort (popularity, descending).
Filtering is as per :ref:`collection addon list endpoint<collection-addon-filtering-param>` - i.e. defaults to only including public add-ons.
Additional add-ons can be returned from the :ref:`Collection Add-on list endpoint<collection-addon-list>`.


.. http:get:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/?with_addons

    .. _collection-detail-object-with-addons:

    :query string filter: The :ref:`filter <collection-addon-filtering-param>` to apply.
    :>json int id: The id for the collection.
    :>json int addon_count: The number of add-ons in this collection.
    :>json array addons: An array of :ref:`addons with notes<collection-addon-detail>`.

... rest as :ref:`collection detail response<collection-detail-object>`


------
Create
------

.. _`collection-create`:

.. note::
    This API requires :doc:`authentication <auth>`.

This endpoint allows a collection to be created under your account.  Any fields
in the :ref:`collection <collection-detail-object>` but not listed below are not settable and will be ignored in the request.

.. http:post:: /api/v4/accounts/account/(int:user_id|string:username)/collections/

    .. _collection-create-request:

    :<json string|null default_locale: The default locale of the description and name fields. Defaults to `en-US`. (See :ref:`translated fields <api-overview-translations>`).
    :<json string|object|null description: The description the author added to the collection. (See :ref:`translated fields <api-overview-translations>`).
    :<json string|object name: The name of the collection. (required) (See :ref:`translated fields <api-overview-translations>`).
    :<json boolean public: Whether the collection is `listed` - publicly viewable.  Defaults to `True`.
    :<json string slug: The name used in the URL (required).


----
Edit
----

.. _`collection-edit`:

.. note::
    This API requires :doc:`authentication <auth>`. If you have
    ``Admin:Curation`` permission you can edit any collection belonging to the
    ``mozilla`` user.


This endpoint allows some of the details for a collection to be updated.  Any fields
in the :ref:`collection <collection-detail-object>` but not listed below are not editable and will be ignored in the patch request.

.. http:patch:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/

    .. _collection-edit-request:

    :<json string default_locale: The default locale of the description and name fields. (See :ref:`translated fields <api-overview-translations>`).
    :<json string|object|null description: The description the author added to the collection. (See :ref:`translated fields <api-overview-translations>`).
    :<json string|object name: The name of the collection. (See :ref:`translated fields <api-overview-translations>`).
    :<json boolean public: Whether the collection is `listed` - publicly viewable.
    :<json string slug: The name used in the URL.


------
Delete
------

.. _`collection-delete`:

.. note::
    This API requires :doc:`authentication <auth>`.

This endpoint allows the collection to be deleted.

.. http:delete:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/



-----------------------
Collection Add-ons List
-----------------------

.. _collection-addon-list:

This endpoint lists the add-ons in a collection, together with collector's notes.

.. http:get:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/

    :query string filter: The :ref:`filter <collection-addon-filtering-param>` to apply.
    :query string sort: The sort parameter. The available parameters are documented in the :ref:`table below <collection-addon-list-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`items <collection-addon-detail-object>` in this collection.


.. _collection-addon-list-sort:

    Available sorting parameters:

    ==============  ==========================================================
         Parameter  Description
    ==============  ==========================================================
             added  Date the add-on was added to the collection, ascending.
        popularity  Number of total weekly downloads of the add-on, ascending.
              name  Add-on name, ascending.
    ==============  ==========================================================

All sort parameters can be reversed, e.g. '-added' for descending dates.
The default sorting is by popularity, descending ('-popularity').
There can only be one sort parameter, multiple orderings are not supported.


.. _collection-addon-filtering-param:

   By default, the collection addon list API will only return public add-ons
   (excluding add-ons that have no approved listed versions, are disabled or
   deleted) - you can change that with the ``filter`` query parameter:

    ================  ========================================================
               Value  Description
    ================  ========================================================
                 all  Show all add-ons in the collection, including those that
                      have non-public statuses.  This still excludes deleted
                      add-ons.
    all_with_deleted  Show all add-ons in the collection, including deleted
                      add-ons too.
    ================  ========================================================


-------------------------
Collection Add-ons Detail
-------------------------

.. _collection-addon-detail:

This endpoint gets details of a single add-on in a collection, together with collector's notes.

.. http:get:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/(int:addon_id|string:slug)/

    .. _collection-addon-detail-object:

    :>json object addon: The :ref:`add-on <addon-detail-object>` for this item.
    :>json string|object|null notes: The collectors notes for this item. (See :ref:`translated fields <api-overview-translations>`).
    :>json int downloads: The downloads that occured via this collection.


-------------------------
Collection Add-ons Create
-------------------------

.. _collection-addon-create:

.. note::
    This API requires :doc:`authentication <auth>`.

This endpoint allows a single add-on to be added to a collection, optionally with collector's notes.

.. http:post:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/

    :<json string addon: The add-on id or slug to be added (required).
    :<json string|object|null notes: The collectors notes for this item. (See :ref:`translated fields <api-overview-translations>`).


-----------------------
Collection Add-ons Edit
-----------------------

.. _collection-addon-edit:

.. note::
    This API requires :doc:`authentication <auth>`. If you have
    ``Admin:Curation`` permission you can edit the add-ons of any collection
    belonging to the ``mozilla`` user. If you have ``Collections:Contribute``
    permission you can edit the add-ons of mozilla's ``Featured Themes``
    collection.

This endpoint allows the collector's notes for single add-on to be updated.

.. http:patch:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/(int:addon_id|string:slug)/

    :<json string|object|null notes: The collectors notes for this item. (See :ref:`translated fields <api-overview-translations>`).


-------------------------
Collection Add-ons Delete
-------------------------

.. _collection-addon-delete:

.. note::
    This API requires :doc:`authentication <auth>`. If you have
    ``Admin:Curation`` permission you can remove add-ons from any collection
    belonging to the ``mozilla`` user. If you have ``Collections:Contribute``
    permission you can remove add-ons from mozilla's ``Featured Themes``
    collection.

This endpoint allows a single add-on to be removed from a collection.

.. http:delete:: /api/v4/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/(int:addon_id|string:slug)/
