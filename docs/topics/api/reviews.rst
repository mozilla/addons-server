=======
Reviews
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

-------------------
List Add-on reviews
-------------------

.. review-list-addon:

This endpoint allows you to fetch reviews for a given add-on.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/

    :query string filter: The :ref:`filter <review-filtering-param>` to apply.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`reviews <review-detail-object>`.

.. _review-filtering-param:

   By default, the review list API will only return not-deleted reviews. You
   can change that with the ``filter=with_deleted`` query parameter, which
   requires the Addons:Edit permission.

----------------------
List reviews by a user
----------------------

.. review-list-user:

This endpoint allows you to fetch reviews posted by a specific user.

.. http:get:: /api/v3/accounts/account/(int:id)/reviews/

    :query string filter: The :ref:`filter <review-filtering-param>` to apply.
    :param int id: The user id.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`reviews <review-detail-object>`.    

------
Detail
------

.. review-detail:

This endpoint allows you to fetch a review by its id.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/(int:id)/

    .. _review-detail-object:

    :>json int id: The review id.
    :>json string|null body: The text of the review.
    :>json string|null: The title of the review.
    :>json int rating: The rating the user gave as part of the review.
    :>json object|null reply: The review object containing the developer reply to this review, if any (The fields ``rating``, ``reply`` and ``version`` are omitted).
    :>json string version: The add-on version string the review applies to.
    :>json object user: Object holding information about the user who posted the review.
    :>json string user.url: The user profile URL.
    :>json string user.name: The user name.

----
Post
----

.. review-list-addon:

This endpoint allows you to post a new review for a given add-on and version.

 .. note::
     Requires authentication.


.. http:post:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/

    :<json string|null body: The text of the review.
    :<json string|null: The title of the review.
    :<json int rating: The rating the user wants to give as part of the review (required).
    :<json int version: The add-on version id the review applies to.


----
Edit
----

.. review-edit-addon:

This endpoint allows you to edit an existing review by its id.

 .. note::
     Requires authentication and Addons:Edit permissions or the user
     account that posted the review.

     Only body, title and rating are allowed for modification.

.. http:patch:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/(int:id)/

    :<json string|null body: The text of the review.
    :<json string|null: The title of the review.
    :<json int rating: The rating the user wants to give as part of the review.


------
Delete
------

.. review-delete-addon:

This endpoint allows you to delete an existing review by its id.

 .. note::
     Requires authentication and Addons:Edit permission or the user
     account that posted the review. Even with the right permission, users can
     not delete a review from somebody else if it was posted on an add-on they
     are listed as a developer of.

.. http:delete:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/(int:id)/


-----
Reply
-----

.. review-list-addon:

This endpoint allows you to reply to an existing user review.

 .. note::
     Requires authentication and either Addons:Edit permission or a user account
     listed as a developer of the add-on.

.. http:post:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/reviews/(int:id)/reply/

    :<json string body: The text of the reply (required).
    :<json string|null: The title of the reply.
