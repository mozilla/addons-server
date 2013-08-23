.. _rocketfuel:

==========
Rocketfuel
==========

Rocketfuel is the consumer client for the Marketplace Publishing Tool. It has some special APIs that are *not recommended* for consumption by other clients.

These APIs will change in conjunction with the Rocketfuel client.


Collections
===========

A collection is a group of applications


Listing
-------

.. http:get:: /api/v1/rocketfuel/collections/

    A listing of all collections.

    .. note:: Authentication is optional.

    **Request**:

    :param category: a category ID.
    :type category: int
    :param region: a region ID.
    :type region: int
    :param carrier: a carrier ID.
    :type carrier: int

Create
------

.. http:post:: /api/v1/rocketfuel/collections/

    Create a collection.

    .. note:: Authentication is required.

    **Request**:

    :param author: the author of the collection.
    :type author: string
    :param carrier: the ID of the carrier to attach this collection to. Defaults
        to ``null``.
    :type carrier: int|null
    :param category: the ID of the category to attach this collection to.
        Defaults to ``null``.
    :type category: int|null
    :param collection_type: the type of collection to create.
    :type collection_type: int
    :param description: a description of the collection. Can be a dict, in which
        case keys are languages and values are each a translation for the
        corresponding language.
    :type description: string|dict
    :param name: the name of the collection. Can be a dict, in which case keys
        are languages and values are each a translation for the corresponding
        language.
    :type name: string|dict
    :param region: the ID of the region to attach this collection to. Defaults
        to ``null``.
    :type region: int|null
    :param slug: a slug to use in URLs for the collection. Automatically
        generated if not specified.
    :type slug: string|null

Detail
------

.. http:get:: /api/v1/rocketfuel/collections/(int:id)/

    Get a single collection.

    .. note:: Authentication is optional.


Update
------

.. http:patch:: /api/v1/rocketfuel/collections/(int:id)/

    Update a collection.

    .. note:: Authentication is required.

    **Request**:

    :param author: the author of the collection.
    :type author: string
    :param carrier: the ID of the carrier to attach this collection to.
    :type carrier: int|null
    :param category: the ID of the category to attach this collection to.
    :type category: int|null
    :param collection_type: the type of the collection.
    :type collection_type: int
    :param description: a description of the collection. Can be a dict, in which case keys are languages and values are each a translation for the corresponding language.
    :type description: string|dict
    :param name: the name of the collection. Can be a dict, in which case keys are languages and values are each a translation for the corresponding language.
    :type name: string|dict
    :param region: the ID of the region to attach this collection to.
    :type region: int|null
    :param slug: a slug to use in URLs for the collection.
    :type slug: string|null


    **Response**:

    A representation of the updated collection will be returned in the response
    body.

    :status 200: collection successfully updated.
    :status 400: invalid request; more details provided in the response body.


Duplicate
---------

.. http:post:: /api/v1/rocketfuel/collections/(int:id)/duplicate/

    Duplicate a collection, creating and returning a new one with the same
    properties and the same apps.

    .. note:: Authentication is required.

    **Request**:

    Any parameter passed will override the corresponding property from the
    duplicated object.

    :param author: the author of the collection.
    :type author: string
    :param carrier: the ID of the carrier to attach this collection to.
    :type carrier: int|null
    :param category: the ID of the category to attach this collection to.
    :type category: int|null
    :param collection_type: the type of the collection.
    :type collection_type: int
    :param description: a description of the collection. Can be a dict, in which case keys are languages and values are each a translation for the corresponding language.
    :type description: string|dict
    :param name: the name of the collection. Can be a dict, in which case keys are languages and values are each a translation for the corresponding language.
    :type name: string|dict
    :param region: the ID of the region to attach this collection to.
    :type region: int|null
    :param slug: a slug to use in URLs for the collection.
    :type slug: string|null

    **Response**:

    A representation of the duplicate collection will be returned in the
    response body.

    :status 201: collection successfully duplicated.
    :status 400: invalid request; more details provided in the response body.


Add Apps
--------

.. http:post:: /api/v1/rocketfuel/collections/(int:id)/add_app/

    Add an application to a single collection.

    .. note:: Authentication is required.

    **Request**:

    :param app: the ID of the application to add to this collection.
    :type app: int

    **Response**:

    A representation of the updated collection will be returned in the response
    body.

    :status 200: app successfully added to collection.
    :status 400: invalid request; more details provided in the response body.


Remove Apps
-----------

.. http:post:: /api/v1/rocketfuel/collections/(int:id)/remove_app/

    Remove an application from a single collection.

    .. note:: Authentication is required.

    **Request**:

    :param app: the ID of the application to remove from this collection.
    :type app: int

    **Response**:

    A representation of the updated collection will be returned in the response
    body.

    :status 200: app successfully removed from collection.
    :status 205: app not a member of the collection.
    :status 400: invalid request; more details provided in the response body.


Reorder Apps
------------

.. http:post:: /api/v1/rocketfuel/collections/(int:id)/reorder/

    Reorder applications in a collection.

    .. note:: Authentication is required.

    **Request**:

    The body of the request must contain a list of apps in their desired order.

    Example:

    .. code-block:: json

        [18, 24, 9]

    **Response**:

    A representation of the updated collection will be returned in the response
    body.

    :status 200: collection successfully reordered.
    :status 400: all apps in the collection not represented in response body.
        For convenience, a list of all apps in the collection will be included
        in the response.
