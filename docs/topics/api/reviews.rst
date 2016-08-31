=======
Reviews
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

-------------
List (add-on)
-------------

.. review-list-addon:

This endpoint allows you to fetch user reviews for a given add-on.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/

    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`reviews <review-detail-object>`.

-------------
List (user)
-------------

.. review-list-user:

This endpoint allows you to fetch reviews posted by a specific user.

.. http:get:: /api/v3/accounts/account/(int:id)/reviews/

    :param int id: The user id.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`reviews <review-detail-object>`.    

------
Detail
------

.. review-detail:

This endpoint allows you to fetch a user review by id.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/(int:id)/

    .. _review-detail-object:

    :>json int id: The review id.
    :>json string|null body: The text of the review.
    :>json string|null: The title of the review.
    :>json int rating: The rating the user gave as part of the review.
    :>json object|null reply: The review object containing the developer reply to this review, if any (The fields ``rating`` and ``reply`` are omitted).
    :>json string version: The add-on version string the review applies to.
    :>json object user: Object holding information about the user who posted the review.
    :>json string user.url: The user profile URL.
    :>json string user.name: The user name.
