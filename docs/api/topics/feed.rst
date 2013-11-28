.. _feed:
.. versionadded:: 2

====
Feed
====

The Marketplace Feed is a stream compromised of a number of *feed items* acting
as containers of items of other types. Currently only
:ref:`collections <rocketfuel>` may be added, but this will be expanded in
the future.

.. _feed-item:

Feed items are represented thusly:

.. code-block:: json

    {
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

.. note::

    ``GET``, ``HEAD``, and ``OPTIONS`` requests to these endpoints may be made
    anonymously. Authentication and the ``Feed:Curate`` permission are required
    to make any other request.


List Feed Items
===============

.. http:get:: /api/v2/feed/items/

    Get a listing of feed items.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of
        :ref:`feed items <feed-item>`.
    :type objects: array


Feed Item Detail
================

.. http:get:: /api/v2/feed/items/(int:id)/

    Get detail of a specific feed item.

    **Request**

    :param id: the ID of the feed item.
    :type id: int

    **Response**

    A serialization of the :ref:`feed item <feed-item>`.


Create a feed item
==================

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

    The following parameters define the content featured in this feed item.
    Exactly one must be specified in the request.

    :param region: the ID of a :ref:`collection <rocketfuel>`.
    :type region: int|null

    .. code-block:: json

        {
            "carrier": null,
            "category": null,
            "collection": 4,
            "region": 1
        }

    **Response**

    A serialization of the newly-created :ref:`feed item <feed-item>`.

    :status 201: successfully created. A ``Location`` header will indicate the
        detail URL of the newly-created feed item.
    :status 400: submission error, see the error message in the response body
        for more detail.
    :status 403: not authorized.


Update a feed item
==================

.. http:put:: /api/v2/feed/items/(int:id)/

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

    The following parameters define the content featured in this feed item.
    Exactly one must be specified in the request.

    :param region: the ID of a :ref:`collection <rocketfuel>`.
    :type region: int|null

    **Response**

    A serialization of the updated :ref:`feed item <feed-item>`.

    :status 200: successfully updated.
    :status 400: submission error, see the error message in the response body
        for more detail.
    :status 403: not authorized.


Delete a feed item
==================

.. http:delete:: /api/v2/feed/items/(int:id)/

    Delete a feed item.

    **Request**

    :param id: the ID of the feed item.
    :type id: int

    **Response**

    :status 204: successfully deleted.
    :status 403: not authorized.
