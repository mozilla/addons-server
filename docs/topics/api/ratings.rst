=======
Ratings
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

------------
List ratings
------------

.. rating-list:

This endpoint allows you to fetch ratings for a given add-on or user. Either
``addon`` or ``user`` query parameters are required, and they can be
combined together.

When ``addon``, ``user`` and ``version`` are passed on the same request,
``page_size`` will automatically be set to ``1``, since an user can only post
one rating per version of a given add-on. This can be useful to find out if a
user has already posted a rating for the current version of an add-on.

.. http:get:: /api/v4/ratings/rating/

    :query string addon: The :ref:`add-on <addon-detail>` id, slug, or guid to fetch ratings from. When passed, the ratings shown will always be the latest posted by each user on this particular add-on (which means there should only be one rating per user in the results), unless the ``version`` parameter is also passed.
    :query string exclude_ratings: Exclude ratings by their ``id``. Multiple ratings can be specified, separated by comma(s).
    :query string filter: The :ref:`filter(s) <rating-filtering-param>` to apply.
    :query string score: Only include ratings that have been given a specific ``score``. Multiple scores can be specified, separated by comma(s).
    :query string show_flags_for: The user id to show flags for. If the request is made with an authenticated user matching this parameter value, a ``flags`` property will be added to the response as described below in :ref:`ratings <rating-detail-object>`.
    :query boolean show_grouped_ratings: Whether or not to show ratings aggregates for this add-on in the response (Use "true"/"1" as truthy values, "0"/"false" as falsy ones).
    :query string show_permissions_for: The user id to show permissions for. If the request is made with an authenticated user matching this parameter value, and the ``addon`` parameter is also present, a ``can_reply`` property will be added to the response as described below.
    :query int user: The user id to fetch ratings from.
    :query int version: The version id to fetch ratings from.
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`ratings <rating-detail-object>`.
    :>json boolean can_reply: Only present if the ``addon`` query parameter and ``show_permissions_for`` parameters are present. A boolean indicating if the user that made the ratings list request can reply to ratings in that list.
    :>json object grouped_ratings: Only present if ``show_grouped_ratings`` query parameter is present. An object with 5 key-value pairs, the keys representing each possible rating (Though a number, it has to be converted to a string because of the JSON formatting) and the values being the number of times the corresponding rating has been posted for this add-on, e.g. ``{"1": 4, "2": 8, "3": 15, "4": 16: "5": 23}``.

.. _rating-filtering-param:

   By default, the rating list API will only return not-deleted ratings, and
   include ratings without text. You can change that with the ``filter`` query
   parameter.  You can filter by multiple values, e.g. ``filter=with_deleted,without_empty_body,with_yours``

    ===================  ======================================================
                  Value  Description
    ===================  ======================================================
           with_deleted  Returns deleted ratings too.  This requires the
                         Addons:Edit permission.
     without_empty_body  Excludes ratings that only contain a rating, and no
                         textual content.
             with_yours  Used in combination `without_empty_body` to include
                         your own ratings, even if they have no text.
    ===================  ======================================================

------
Detail
------

.. rating-detail:

This endpoint allows you to fetch a rating by its id.

.. note::

    Users with ``Addons:Edit`` permission will be able to see deleted ratings.
    Use the ``is_deleted`` property to distinguish those from normal ratings
    everyone is able to see.


.. http:get:: /api/v4/ratings/rating/(int:id)/

    .. _rating-detail-object:

    :query string show_flags_for: The user id to show flags for. If the request is made with an authenticated user matching this parameter value, a ``flags`` property will be added to the response as described below.
    :>json int id: The rating id.
    :>json object addon: A simplified :ref:`add-on <addon-detail-object>` object that contains only a few properties: ``id``, ``name``, ``icon_url`` and ``slug``.
    :>json string|null body: The text of the rating.
    :>json boolean is_deleted: Boolean indicating whether the rating has been deleted or not.
    :>json boolean is_latest: Boolean indicating whether the rating is the latest posted by the user on the same add-on.
    :>json int previous_count: The number of ratings posted by the user on the same add-on before this one.
    :>json object flags[]: A list of flags the user requesting has previously applied to this rating (that haven't been processed by moderators already). Only present if ``show_flags_for`` parameter sent.
    :>json string flags.flag: A :ref:`constant<rating-flag-constants>` describing the reason behind the flagging.
    :>json string|null flags.note: A note to explain further the reason behind the flagging if ``flag`` was ``rating_flag_reason_other``; null otherwise.
    :>json int score: The score the user gave as part of the rating.
    :>json object|null reply: The rating object containing the developer reply to this rating, if any (The fields ``rating``, ``reply`` and ``version`` are omitted).
    :>json int version.id: The add-on version id the rating applies to.
    :>json string version.version: The add-on version string the rating applies to.
    :>json object user: Object holding information about the user who posted the rating.
    :>json string user.id: The user id.
    :>json string user.name: The user name.
    :>json string user.url: The user profile URL.
    :>json string user.username: The user username.

----
Post
----

.. rating-post:

This endpoint allows you to post a new rating for a given add-on and version.
If successful a :ref:`rating object <rating-detail-object>` is returned.

 .. note::
     Requires authentication.


.. http:post:: /api/v4/ratings/rating/

    :<json string addon: The add-on id the rating applies to (required).
    :<json string|null body: The text of the rating.
    :<json int score: The score the user wants to give as part of the rating (required).
    :<json int version: The add-on version id the rating applies to (required).

----
Edit
----

.. rating-edit:

This endpoint allows you to edit an existing rating by its id.
If successful a :ref:`rating object <rating-detail-object>` is returned.

 .. note::
     Requires authentication and Addons:Edit permissions or the user
     account that posted the rating.

     Only body and score are allowed for modification.

.. http:patch:: /api/v4/ratings/rating/(int:id)/

    :<json string|null body: The text of the rating.
    :<json int score: The score the user wants to give as part of the rating.


------
Delete
------

.. rating-delete:

This endpoint allows you to delete an existing rating by its id.

 .. note::
     Requires authentication and Addons:Edit permission or the user
     account that posted the rating. Even with the right permission, users can
     not delete a rating from somebody else if it was posted on an add-on they
     are listed as a developer of.

.. http:delete:: /api/v4/ratings/rating/(int:id)/


-----
Reply
-----

.. rating-reply:

This endpoint allows you to reply to an existing user rating.
If successful a :ref:`rating reply object <rating-detail-object>` is returned -
a `rating` object but with the fields ``rating``, ``reply`` and ``version`` omitted.

 .. note::
     Requires authentication and either Addons:Edit permission or a user account
     listed as a developer of the add-on.

.. http:post:: /api/v4/ratings/rating/(int:id)/reply/

    :<json string body: The text of the reply (required).


----
Flag
----

.. rating-flag:

This endpoint allows you to flag an existing user rating, to let a moderator know
that something may be wrong with it.


 .. note::
     Requires authentication and a user account different from the one that
     posted the rating.

.. http:post:: /api/v4/ratings/rating/(int:id)/flag/

    :<json string flag: A :ref:`constant<rating-flag-constants>` describing the reason behind the flagging.
    :<json string|null note: A note to explain further the reason behind the flagging.
        This field is required if the flag is ``rating_flag_reason_other``, and passing it will automatically change the flag to that value.
    :>json object: If successful, an object with a ``msg`` property containing a success message. If not, an object indicating which fields contain errors.

.. _rating-flag-constants:

    Available constants for the ``flag`` property:

    ===============================  ==========================================
                          Constant    Description
    ===============================  ==========================================
            rating_flag_reason_spam  Spam or otherwise non-rating content
        rating_flag_reason_language  Inappropriate language/dialog
     rating_flag_reason_bug_support  Misplaced bug report or support request
           rating_flag_reason_other  Other (please specify)
    ===============================  ==========================================
