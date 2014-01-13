.. _feed:
.. versionadded:: 2

====
Feed
====

The Marketplace Feed is a stream of content relevant to the user displayed on
the Marketplace home page. The feed is comprised of a number of :ref:`feed items
<feed-items>`, each containing a singular of piece of content. Currently, the
feed may include:

- :ref:`Apps <feed-apps>`
- :ref:`Collections <collections>`

.. note::

    ``GET``, ``HEAD``, and ``OPTIONS`` requests to these endpoints may be made
    anonymously. Authentication and the ``Feed:Curate`` permission are required
    to make any other request.


.. _feed-items:

----------
Feed Items
----------

Feed items are represented thusly:

.. code-block:: json

    {
        "app": null,
        "carrier": "telefonica",
        "category": null,
        "collection": {
            "data": "..."
        }
        "id": 47,
        "item_type": "collection",
        "region": "br",
        "resource_url": "/api/v2/feed/items/47/"
    }

``app``
    *object|null* - the full representation of a :ref:`feed app <feed-apps>`.
``carrier``
    *string|null* - the slug of a :ref:`carrier <carriers>`. If
    defined, this feed item will only be available by users of that carrier.
``category``
    *int|null* - the ID of a :ref:`category <categories>`. If defined, this feed
    item will only be available to users browsing that category.
``collection``
    *object|null* - the full representation of a  :ref:`collection
    <collections>`.
``id``
    *int* the ID of this feed item.
``item_type``
    *string* - the type of object being represented by this feed item. This will
    always be usable as a key on the feed item instance to fetch that object's
    data (i.e. ``feeditem[feeditem['item_type']]`` will always be non-null).
``resource_url``
    *string* - the permanent URL for this feed item. 
``region``
    *string|null* - the slug of a :ref:`region <regions>`. If defined, this feed
    item will only be available in that region.


List
====

.. http:get:: /api/v2/feed/items/

    A listing of feed items.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of
        :ref:`feed items <feed-items>`.
    :type objects: array


Detail
======

.. http:get:: /api/v2/feed/items/(int:id)/

    Detail of a specific feed item.

    **Request**

    :param id: the ID of the feed item.
    :type id: int

    **Response**

    A representation of the :ref:`feed item <feed-items>`.


Create
======

.. http:post:: /api/v2/feed/items/

    Create a feed item.

    **Request**

    :param carrier: the ID of a :ref:`carrier <carriers>`. If defined, it will
        restrict this feed item to only be viewed by users of this carrier.
    :type carrier: int|null
    :param category: the ID of a :ref:`category <categories>`. If defined, it
        will restrict this feed item to only be viewed by users browsing this
        category.
    :type category: int|null
    :param region: the ID of a :ref:`region <regions>`. If defined, it will
        restrict this feed item to only be viewed in this region.
    :type region: int|null

    The following parameters define the object contained by this feed item.
    Only one may be set on a feed item.

    :param app: the ID of a :ref:`feed app <feed-apps>`.
    :type app: int|null
    :param collection: the ID of a :ref:`collection <rocketfuel>`.
    :type collection: int|null

    .. code-block:: json

        {
            "carrier": null,
            "category": null,
            "collection": 4,
            "region": 1
        }

    **Response**

    A representation of the newly-created :ref:`feed item <feed-items>`.

    :status 201: successfully created.
    :status 400: submission error, see the error message in the response body
        for more detail.
    :status 403: not authorized.


Update
======

.. http:patch:: /api/v2/feed/items/(int:id)/

    Update the properties of a feed item.

    **Request**

    :param carrier: the ID of a :ref:`carrier <carriers>`. If defined, it will
        restrict this feed item to only be viewed by users of this carrier.
    :type carrier: int|null
    :param category: the ID of a :ref:`category <categories>`. If defined, it
        will restrict this feed item to only be viewed by users browsing this
        category.
    :type category: int|null
    :param region: the ID of a :ref:`region <regions>`. If defined, it will
        restrict this feed item to only be viewed in this region.
    :type region: int|null

    The following parameters define the object contained by this feed item.
    Only one may be set on a feed item.

    :param app: the ID of a :ref:`feed app <feed-apps>`.
    :type app: int|null
    :param collection: the ID of a :ref:`collection <rocketfuel>`.
    :type collection: int|null

    **Response**

    A serialization of the updated :ref:`feed item <feed-items>`.

    :status 200: successfully updated.
    :status 400: submission error, see the error message in the response body
        for more detail.
    :status 403: not authorized.


Delete
======

.. http:delete:: /api/v2/feed/items/(int:id)/

    Delete a feed item.

    **Request**

    :param id: the ID of the feed item.
    :type id: int

    **Response**

    :status 204: successfully deleted.
    :status 403: not authorized.


.. _feed-apps:

---------
Feed Apps
---------

A feed app is a thin wrapper around an :ref:`app <app>`, object containing
additional metadata related to its feature in the feed.

Feed apps are represented thusly:

.. code-block:: json

    {
        "app": {
            "data": "..."
        },
        "description": {
            "en-US": "A featured app",
            "fr": "Une application sélectionnée"
        },
        "id": 1
        "preview": null,
        "rating": null,
        "url": "/api/v2/feed/apps/1/"
    }

``app``
    *object* - the full representation of an :ref:`app <app>`.
``description``
    *string|null* - a :ref:`translated <overview-translations>` description of
    the app being featured.
``id``
    *int* - the ID of this feed app.
``preview``
    *object|null* - a featured :ref:`preview <screenshot-response-label>`
    (screenshot or video) of the app.
``rating``
    *object|null* - a featured :ref:`rating <ratings>` of the app.
``url``
    *string|null* - the permanent URL for this feed app.


List
====

.. http:get:: /api/v2/feed/apps/

    A listing of feed apps.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of
        :ref:`feed apps <feed-apps>`.
    :type objects: array


Detail
======

.. http:get:: /api/v2/feed/apps/(int:id)/

    Detail of a specific feed app.

    **Request**

    :param id: the ID of the feed app.
    :type id: int

    **Response**

    A representation of the :ref:`feed app <feed-apps>`.


Create
======

.. http:post:: /api/v2/feed/apps/

    Create a feed app.

    **Request**

    :param app: the ID of a :ref:`feed app <feed-apps>`.
    :type app: int|null
    :param description: a :ref:`translated <overview-translations>` description
        of the app being featured.
    :type description: object|null
    :param preview: the ID of a :ref:`preview <screenshot-response-label>` to
        feature with the app.
    :type preview: int|null
    :param rating: the ID of a :ref:`rating <ratings>` to feature with the app.
    :type rating: int|null

    .. code-block:: json

        {
            "app": 710,
            "description": {
                "en-US": "A featured app",
                "fr": "Une application sélectionnée"
            },
            "rating": 13401
        }

    **Response**

    A representation of the newly-created :ref:`feed app <feed-apps>`.

    :status 201: successfully created.
    :status 400: submission error, see the error message in the response body
        for more detail.
    :status 403: not authorized.

Update
======

.. http:patch:: /api/v2/feed/apps/(int:id)/

    Update the properties of a feed app.

    **Request**

    :param app: the ID of a :ref:`feed app <feed-apps>`.
    :type app: int|null
    :param description: a :ref:`translated <overview-translations>` description
        of the app being featured.
    :type description: object|null
    :param preview: the ID of a :ref:`preview <screenshot-response-label>` to
        feature with the app.
    :type preview: int|null
    :param rating: the ID of a :ref:`rating <ratings>` to feature with the app.
    :type rating: int|null

    **Response**

    A representation of the newly-created :ref:`feed app <feed-apps>`.

    :status 200: successfully updated.
    :status 400: submission error, see the error message in the response body
        for more detail.
    :status 403: not authorized.


Delete
======

.. http:delete:: /api/v2/feed/apps/(int:id)/

    Delete a feed app.

    **Request**

    :param id: the ID of the feed app.
    :type id: int

    **Response**

    :status 204: successfully deleted.
    :status 403: not authorized.
