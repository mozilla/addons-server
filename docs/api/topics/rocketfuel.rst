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


Create
------

.. http:post:: /api/v1/rocketfuel/collections/

    Create a collection.

    .. note:: Authentication is required.

    **Request**:

    :param name: the name of the collection.
    :type name: string
    :param description: a description of the collection.
    :type description: string


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

    :param name: the name of the collection.
    :type name: string
    :param description: a description of the collection.
    :type description: string

    **Response**:

    A representation of the updated collection will be returned in the response
    body.

    :status 200: collection successfully updated.
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
