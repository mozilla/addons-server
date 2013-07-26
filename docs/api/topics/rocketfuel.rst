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


.. http:post:: /api/v1/rocketfuel/collections/(int:id)/add_app/

    Add an application to a single collection.

    .. note:: Authentication is required.

    **Request**:

    :param app: the ID of the application to add to this collection.
    :type app: int
