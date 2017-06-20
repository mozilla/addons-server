===========
Collections
===========

The following API endpoints cover user created collections.


----
List
----

.. _collection-list:

.. note::
    This API requires :doc:`authentication <auth>` and `Collections:Edit`
    permission to list collections other than your own.

This endpoint allows you to list all collections authored by the specified user.
The results are sorted by the most recently updated collection first.


.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/collections/

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
If your account has the `Collections:Edit` permission then you can access any collection.

.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/

    .. _collection-detail-object:

    :>json int id: The id for the collection.
    :>json int addon_count: The number of add-ons in this collection.
    :>json int author.id: The id of the author (creator) of the collection.
    :>json string author.name: The name of the author.
    :>json string author.url: The link to the profile page for of the author.
    :>json string default_locale: The default locale of the description and name fields. (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null description: The description the author added to the collection. (See :ref:`translated fields <api-overview-translations>`).
    :>json string modified: The date the collection was last updated.
    :>json string|object name: The name of the collection. (See :ref:`translated fields <api-overview-translations>`).
    :>json boolean public: Whether the collection is `listed` - publicly viewable.
    :>json string slug: The name used in the URL.
    :>json string url: The (absolute) collection detail URL.
    :>json string uuid: A unique identifier for this collection; primarily used to count addon installations that come via this collection.


------
Create
------

.. _`collection-create`:

.. note::
    This API requires :doc:`authentication <auth>`.

This endpoint allows a collection to be created under your account.  Any fields
in the :ref:`collection <collection-detail-object>` but not listed below are not settable and will be ignored in the request.

.. http:post:: /api/v3/accounts/account/(int:user_id|string:username)/collections/

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
    This API requires :doc:`authentication <auth>` and `Collections:Edit`
    permission to edit collections other than your own.

This endpoint allows some of the details for a collection to be updated.  Any fields
in the :ref:`collection <collection-detail-object>` but not listed below are not editable and will be ignored in the patch request.

.. http:patch:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/

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
    This API requires :doc:`authentication <auth>` and `Collections:Edit`
    permission to delete collections other than your own.

This endpoint allows the collection to be deleted.

.. http:delete:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/



-----------------------
Collection Add-ons List
-----------------------

.. _collection-addon-list:

This endpoint lists the add-ons in a collection, together with collector's notes.

.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/

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


-------------------------
Collection Add-ons Detail
-------------------------

.. _collection-addon-detail:

This endpoint gets details of a single add-on in a collection, together with collector's notes.

.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/(int:addon_id|string:slug)/

    .. _collection-addon-detail-object:

    :>json object addon: The :ref:`add-on <addon-detail-object>` for this item.
    :>json string|object|null notes: The collectors notes for this item. (See :ref:`translated fields <api-overview-translations>`).
    :>json int downloads: The downloads that occured via this collection.


-------------------------
Collection Add-ons Create
-------------------------

.. _collection-addon-create:

.. note::
    This API requires :doc:`authentication <auth>` and `Collections:Edit`
    permission to edit collections other than your own.

This endpoint allows a single add-on to be added to a collection, optionally with collector's notes.

.. http:post:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/

    :<json string addon: The add-on id or slug to be added (required).
    :<json string|object|null notes: The collectors notes for this item. (See :ref:`translated fields <api-overview-translations>`).


-----------------------
Collection Add-ons Edit
-----------------------

.. _collection-addon-edit:

.. note::
    This API requires :doc:`authentication <auth>` and `Collections:Edit`
    permission to edit collections other than your own.

This endpoint allows the collector's notes for single add-on to be updated.

.. http:patch:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/(int:addon_id|string:slug)/

    :<json string|object|null notes: The collectors notes for this item. (See :ref:`translated fields <api-overview-translations>`).


-------------------------
Collection Add-ons Delete
-------------------------

.. _collection-addon-delete:

.. note::
    This API requires :doc:`authentication <auth>` and `Collections:Edit`
    permission to edit collections other than your own.

This endpoint allows a single add-on to be removed from a collection.

.. http:delete:: /api/v3/accounts/account/(int:user_id|string:username)/collections/(string:collection_slug)/addons/(int:addon_id|string:slug)/
