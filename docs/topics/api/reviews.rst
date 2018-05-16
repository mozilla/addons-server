=======
Reviews
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

------------
List reviews
------------

.. review-list:

This endpoint allows you to fetch reviews for a given add-on or user. Either
``addon`` or ``user`` query parameters are required, and they can be
combined together.

When ``addon``, ``user`` and ``version`` are passed on the same request,
``page_size`` will automatically be set to ``1``, since an user can only post
one review per version of a given add-on. This can be useful to find out if a
user has already posted a review for the current version of an add-on.

.. http:get:: /api/v4/reviews/review/

    :query string addon: The :ref:`add-on <addon-detail>` id, slug, or guid to fetch reviews from. When passed, the reviews shown will always be the latest posted by each user on this particular add-on (which means there should only be one review per user in the results), unless the ``version`` parameter is also passed.
    :query string filter: The :ref:`filter(s) <review-filtering-param>` to apply.
    :query string user: The user id to fetch reviews from.
    :query boolean show_grouped_ratings: Whether or not to show ratings aggregates for this add-on in the response (Use "true"/"1" as truthy values, "0"/"false" as falsy ones).
    :query string version: The version id to fetch reviews from.
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`reviews <review-detail-object>`.
    :>json object grouped_ratings: Only present if ``show_grouped_ratings`` query parameter is present. An object with 5 key-value pairs, the keys representing each possible rating (Though a number, it has to be converted to a string because of the JSON formatting) and the values being the number of times the corresponding rating has been posted for this add-on, e.g. ``{"1": 4, "2": 8, "3": 15, "4": 16: "5": 23}``.

.. _review-filtering-param:

   By default, the review list API will only return not-deleted reviews, and
   include reviews without text. You can change that with the ``filter`` query
   parameter.  You can filter by multiple values, e.g. ``filter=with_deleted,without_empty_body,with_yours``

    ===================  ======================================================
                  Value  Description
    ===================  ======================================================
           with_deleted  Returns deleted reviews too.  This requires the
                         Addons:Edit permission.
     without_empty_body  Excludes reviews that only contain a rating, and no
                         textual content.
             with_yours  Used in combination `without_empty_body` to include
                         your own reviews, even if they have no text.
    ===================  ======================================================

------
Detail
------

.. review-detail:

This endpoint allows you to fetch a review by its id.

.. http:get:: /api/v4/reviews/review/(int:id)/

    .. _review-detail-object:

    :>json int id: The review id.
    :>json object addon: An object included for convenience that contains only two properties: ``id`` and ``slug``, corresponding to the add-on id and slug.
    :>json string|null body: The text of the review.
    :>json boolean is_latest: Boolean indicating whether the review is the latest posted by the user on the same add-on.
    :>json int previous_count: The number of reviews posted by the user on the same add-on before this one.
    :>json int rating: The rating the user gave as part of the review.
    :>json object|null reply: The review object containing the developer reply to this review, if any (The fields ``rating``, ``reply`` and ``version`` are omitted).
    :>json string|null title: The title of the review.
    :>json int version.id: The add-on version id the review applies to.
    :>json string version.version: The add-on version string the review applies to.
    :>json object user: Object holding information about the user who posted the review.
    :>json string user.id: The user id.
    :>json string user.name: The user name.
    :>json string user.url: The user profile URL.
    :>json string user.username: The user username.

----
Post
----

.. review-post:

This endpoint allows you to post a new review for a given add-on and version.
If successful a :ref:`review object <review-detail-object>` is returned.

 .. note::
     Requires authentication.


.. http:post:: /api/v4/reviews/review/

    :<json string addon: The add-on id the review applies to (required).
    :<json string|null body: The text of the review.
    :<json string|null title: The title of the review.
    :<json int rating: The rating the user wants to give as part of the review (required).
    :<json int version: The add-on version id the review applies to (required).

----
Edit
----

.. review-edit:

This endpoint allows you to edit an existing review by its id.
If successful a :ref:`review object <review-detail-object>` is returned.

 .. note::
     Requires authentication and Addons:Edit permissions or the user
     account that posted the review.

     Only body, title and rating are allowed for modification.

.. http:patch:: /api/v4/reviews/review/(int:id)/

    :<json string|null body: The text of the review.
    :<json string|null title: The title of the review.
    :<json int rating: The rating the user wants to give as part of the review.


------
Delete
------

.. review-delete:

This endpoint allows you to delete an existing review by its id.

 .. note::
     Requires authentication and Addons:Edit permission or the user
     account that posted the review. Even with the right permission, users can
     not delete a review from somebody else if it was posted on an add-on they
     are listed as a developer of.

.. http:delete:: /api/v4/reviews/review/(int:id)/


-----
Reply
-----

.. review-reply:

This endpoint allows you to reply to an existing user review.
If successful a :ref:`review reply object <review-detail-object>` is returned.

 .. note::
     Requires authentication and either Addons:Edit permission or a user account
     listed as a developer of the add-on.

.. http:post:: /api/v4/reviews/review/(int:id)/reply/

    :<json string body: The text of the reply (required).
    :<json string|null title: The title of the reply.


----
Flag
----

.. review-flag:

This endpoint allows you to flag an existing user review, to let a moderator know
that something may be wrong with it.


 .. note::
     Requires authentication and a user account different from the one that
     posted the review.

.. http:post:: /api/v4/reviews/review/(int:id)/flag/

    :<json string flag: A :ref:`constant<review-flag-constants>` describing the reason behind the flagging.
    :<json string|null note: A note to explain further the reason behind the flagging.
        This field is required if the flag is ``review_flag_reason_other``, and passing it will automatically change the flag to that value.
    :>json object: If successful, an object with a ``msg`` property containing a success message. If not, an object indicating which fields contain errors.

.. _review-flag-constants:

    Available constants for the ``flag`` property:

    ===============================  ==========================================
                          Constant    Description
    ===============================  ==========================================
            review_flag_reason_spam  Spam or otherwise non-review content
        review_flag_reason_language  Inappropriate language/dialog
     review_flag_reason_bug_support  Misplaced bug report or support request
           review_flag_reason_other  Other (please specify)
    ===============================  ==========================================
