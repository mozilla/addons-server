.. _rocketfuel:

==========
Rocketfuel
==========

Rocketfuel is the consumer client for the Marketplace Publishing Tool. It has some special APIs that are *not recommended* for consumption by other clients.

These APIs will change in conjunction with the Rocketfuel client.


Collections
===========

A collection is a group of applications

.. http:get:: /api/v1/rocketfuel/collections/

    A listing of all collections.

    .. note:: Authentication is optional.


.. http:post:: /api/v1/rocketfuel/collections/

    Create a collection.

    .. note:: Authentication is required.

    **Request**:

    :param name: the name of the collection.
    :type name: string
    :param description: a description of the collection.
    :type description: string


.. http:get:: /api/v1/rocketfuel/collections/(int:id)/

    Get a single collection.

    .. note:: Authentication is optional.


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
