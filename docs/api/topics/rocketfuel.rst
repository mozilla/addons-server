.. _rocketfuel:

==========
Rocketfuel
==========

Rocketfuel is the consumer client for the Marketplace Publishing Tool. It has
some special APIs that are *not recommended* for consumption by other clients.

These APIs will change in conjunction with the Rocketfuel client, which is
under active development.

.. warning:: This API is for internal use only at this time. It SHOULD NOT be
    used externally by third parties. It is not considered stable and WILL
    change over time.


.. _collections:

Collections
===========

A collection is a group of applications


.. note::

    The `name` and `description` fields are user-translated fields and have
    a dynamic type depending on the query.
    See :ref:`translations <overview-translations>`.


Listing
-------

.. http:get:: /api/v1/rocketfuel/collections/

    A listing of all collections.

    .. note:: Authentication is optional.

    **Request**:

    The following query string parameters can be used to filter the results:

    :param cat: a category ID/slug.
    :type cat: int|string
    :param region: a region ID/slug.
    :type region: int|string
    :param carrier: a carrier ID/slug.
    :type carrier: int|string

    Filtering on null values is done by omiting the value for the corresponding
    parameter in the query string.

.. _rocketfuel-fallback:

    If no results are found with the filters specified, the API will
    automatically use a fallback mechanism and try to change the values to null
    in order to try to find some results.

    The order in which the filters are set to null is:
        1. `region`
        2. `carrier`
        3. `region` and `carrier`.

    In addition, if that fallback mechanism is used, HTTP responses will have an
    additional `API-Fallback` header, containing the fields which were set to
    null to find the returned results, separated by a comma if needed, like this:

    `API-Fallback: region, carrier`

Create
------

.. http:post:: /api/v1/rocketfuel/collections/

    Create a collection.

    .. note:: Authentication and the 'Collections:Curate' permission are
        required.

    **Request**:

    :param author: the author of the collection.
    :type author: string
    :param background_color: the background of the overlay on the image when
        collection is displayed (hex-formatted, e.g. "#FF00FF"). Only applies to
        curated collections (i.e. when collection_type is 0).
    :type background_color: string|null
    :param can_be_hero: whether the collection may be featured with a hero
        graphic. This may only be set to ``true`` for operator shelves. Defaults
        to ``false``.
    :type can_be_hero: boolean
    :param carrier: the ID of the carrier to attach this collection to. Defaults
        to ``null``.
    :type carrier: int|null
    :param category: the ID of the category to attach this collection to.
        Defaults to ``null``.
    :type category: int|null
    :param collection_type: the type of collection to create.
    :type collection_type: int
    :param description: a description of the collection.
    :type description: string|object
    :param is_public: an indication of whether the collection should be
        displayed in consumer-facing pages. Defaults to ``false``.
    :type is_public: boolean
    :param name: the name of the collection.
    :type name: string|object
    :param region: the ID of the region to attach this collection to. Defaults
        to ``null``.
    :type region: int|null
    :param slug: a slug to use in URLs for the collection. Automatically
        generated if not specified.
    :type slug: string|null
    :param text_color: the color of the text displayed on the overlay on the
        image when collection is displayed (hex-formatted, e.g. "#FF00FF"). Only
        applies to curated collections (i.e. when collection_type is 0).
    :type text_color: string|null


Detail
------

.. http:get:: /api/v1/rocketfuel/collections/(int:id|string:slug)/

    Get a single collection.

    .. note:: Authentication is optional.


Update
------

.. http:patch:: /api/v1/rocketfuel/collections/(int:id|string:slug)/

    Update a collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

    .. note:: The ``can_be_hero`` field may not be modified unless you have the
        ``Collections:Curate`` permission, even if you have curator-level
        access to the collection.

    **Request**:

    :param author: the author of the collection.
    :type author: string
    :param can_be_hero: whether the collection may be featured with a hero
        graphic. This may only be set to ``true`` for operator shelves. Defaults
        to ``false``.
    :type can_be_hero: boolean
    :param carrier: the ID of the carrier to attach this collection to.
    :type carrier: int|null
    :param category: the ID of the category to attach this collection to.
    :type category: int|null
    :param collection_type: the type of the collection.
    :type collection_type: int
    :param description: a description of the collection.
    :type description: string|object
    :param name: the name of the collection.
    :type name: string|object
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

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

    .. note:: The ``can_be_hero`` field may not be modified unless you have the
        ``Collections:Curate`` permission, even if you have curator-level
        access to the collection.

    **Request**:

    Any parameter passed will override the corresponding property from the
    duplicated object.

    :param author: the author of the collection.
    :type author: string
    :param can_be_hero: whether the collection may be featured with a hero
        graphic. This may only be set to ``true`` for operator shelves. Defaults
        to ``false``.
    :type can_be_hero: boolean
    :param carrier: the ID of the carrier to attach this collection to.
    :type carrier: int|null
    :param category: the ID of the category to attach this collection to.
    :type category: int|null
    :param collection_type: the type of the collection.
    :type collection_type: int
    :param description: a description of the collection.
    :type description: string|object
    :param name: the name of the collection.
    :type name: string|object
    :param region: the ID of the region to attach this collection to.
    :type region: int|null
    :param slug: a slug to use in URLs for the collection.
    :type slug: string|null

    **Response**:

    A representation of the duplicate collection will be returned in the
    response body.

    :status 201: collection successfully duplicated.
    :status 400: invalid request; more details provided in the response body.


Delete
------

.. http:delete:: /api/v1/rocketfuel/collections/(int:id|string:slug)/

    Delete a single collection.

    .. note:: Authentication and the 'Collections:Curate' permission are
        required.

    **Response**:

    :status 204: collection successfully deleted.
    :status 400: invalid request; more details provided in the response body.
    :status 403: not authenticated or authenticated without permission; more
        details provided in the response body.


Add Apps
--------

.. http:post:: /api/v1/rocketfuel/collections/(int:id|string:slug)/add_app/

    Add an application to a single collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

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

.. http:post:: /api/v1/rocketfuel/collections/(int:id|string:slug)/remove_app/

    Remove an application from a single collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

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

.. http:post:: /api/v1/rocketfuel/collections/(int:id|string:slug)/reorder/

    Reorder applications in a collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

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

Image
-----

.. http:get:: /api/v1/rocketfuel/collections/(int:id|string:slug)/image/

    Get the image for a collection.

    .. note:: Authentication is optional.


.. http:put:: /api/v1/rocketfuel/collections/(int:id|string:slug)/image/

    Set the image for a collection. Accepts a data URI as the request
    body containing the image, rather than a JSON object.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.


.. http:delete:: /api/v1/rocketfuel/collections/(int:id|string:slug)/image/

    Delete the image for a collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.


Curators
========

Users can be given object-level access to collections if they are marked as
`curators`. The following API endpoints allow manipulation of a collection's
curators:

Listing
-------

.. http:get:: /api/v1/rocketfuel/collections/(int:id|string:slug)/curators/

    Get a list of curators for a collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

    **Response**:

    Example:

    .. code-block:: json

        [
            {
                'display_name': 'Basta',
                'email': 'support@bastacorp.biz',
                'id': 30
            },
            {
                'display_name': 'Cvan',
                'email': 'chris@vans.com',
                'id': 31
            }
        ]


Add Curator
-----------

.. http:post:: /api/v1/rocketfuel/collections/(int:id|string:slug)/add_curator/

    Add a curator to this collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

    **Request**:

    :param user: the ID or email of the user to add as a curator of this
        collection.
    :type user: int|string

    **Response**:

    A representation of the updated list of curators for this collection will be
    returned in the response body.

    :status 200: user successfully added as a curator of this collection.
    :status 400: invalid request; more details provided in the response body.
    :status 403: not authenticated or authenticated without permission; more
        details provided in the response body.


Remove Curator
--------------

.. http:post:: /api/v1/rocketfuel/collections/(int:id|string:slug)/remove_curator/

    Remove a curator from this collection.

    .. note:: Authentication and one of the 'Collections:Curate' permission or
        curator-level access to the collection are required.

    **Request**:

    :param user: the ID or email of the user to remove as a curator of this
        collection.
    :type user: int|string

    **Response**:

    :status 205: user successfully removed as a curator of this collection.
    :status 400: invalid request; more details provided in the response body.
    :status 403: not authenticated or authenticated without permission; more
        details provided in the response body.
