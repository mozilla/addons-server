.. _ratings:

=======
Ratings
=======

These endpoints allow the retrieval, creation, and modification of ratings on
apps in Marketplace.


_`List`
=======

.. http:get:: /api/v1/apps/rating/

    Get a list of ratings from the Marketplace

    .. note:: Authentication is optional.

    **Request**:

    :query app: the ID or slug of the app whose ratings are to be returned.
    :query user: the ID of the user or `mine` whose ratings are to be returned.

    The value `mine` can be used to filter ratings belonging to the currently
    logged in user.

    Plus standard :ref:`list-query-params-label`.

    **Response**:

    .. code-block:: json

        {
            "meta": {
                "limit": 20,
                "next": "/api/v1/apps/rating/?limit=20&offset=20",
                "offset": 0,
                "previous": null,
                "total_count": 391
            },
            "info": {
                "average": "3.4",
                "slug": "marble-run"
            },
            "objects": [
                {
                    "app": "/api/v1/apps/app/18/",
                    "body": "This app is top notch. Aces in my book!",
                    "created": "2013-04-17T15:25:16",
                    "is_author": true,
                    "modified": "2013-04-17T15:34:19",
                    "rating": 5,
                    "resource_uri": "/api/v1/apps/rating/19/",
                    "report_spam": "/api/v1/apps/rating/19/flag",
                    "user": {
                        "display_name": "chuck",
                        "resource_uri": "/api/v1/account/settings/27/"
                    },
                    "version": {
                        "name": "1.0",
                        "latest": true
                    }
                }
            ]
        }

    :param is_author: whether the authenticated user is the author of the rating.
                     Parameter not present in anonymous requests.
    :type is_author: boolean

    :status 200: success.
    :status 400: submission error.


_`Detail`
=========

.. http:get:: /api/v1/apps/rating/(int:id)/

    Get a single rating from the Marketplace using its `resource_uri` from the
    `List`_.

    .. note:: Authentication is optional.

    **Response**:

    .. code-block:: json

        {
            "app": "/api/v1/apps/app/18/",
            "body": "This app is top notch. Aces in my book!",
            "created": "2013-04-17T15:25:16",
            "is_author": true,
            "modified": "2013-04-17T15:34:19",
            "rating": 5,
            "resource_uri": "/api/v1/apps/rating/19/",
            "user": {
                "display_name": "chuck",
                "resource_uri": "/api/v1/account/settings/27/"
            },
            "version": {
                "name": "1.0",
                "latest": true
            }
        }

    :param is_author: whether the authenticated user is the author of the rating.
                     Parameter not present in anonymous requests.
    :type is_author: boolean

    :status 200: success.
    :status 400: submission error.


_`Create`
=========

.. http:post:: /api/v1/apps/rating/

    Create a rating.

    .. note:: Authentication required.

    **Request**:

    :param app: the ID of the app being reviewed
    :param body: text of the rating
    :param rating: an integer between (and inclusive of) 1 and 5, indicating the
        numeric value of the rating

    The user making the rating is inferred from the authentication details.

    .. code-block:: json

        {
            "app": 18,
            "body": "This app is top notch. Aces in my book!",
            "rating": 5
        }


    **Response**:

    .. code-block:: json

        {
            "app": 18,
            "body": "This app is top notch. Aces in my book!",
            "rating": 5
        }

    :status 201: successfully created.
    :status 400: invalid submission.
    :status 403: user not allowed to rate app, because the user is an author of
        the app or because it is a paid app that the user has not purchased.
    :status 409: the user has previously rated the app, so `Update`_ should be
        used instead.


_`Update`
=========

.. http:put:: /api/v1/apps/rating/(int:rating_id)/

    Update a rating from the Marketplace using its `resource_uri` from the
    `List`_.

    .. note:: Authentication required.

    **Request**:

    :param body: text of the rating
    :param rating: an integer between (and inclusive of) 1 and 5, indicating the
        numeric value of the rating

    The user making the rating is inferred from the authentication details.

    .. code-block:: json

        {
            "body": "It stopped working. All dueces, now.",
            "rating": 2
        }

    **Response**:

    .. code-block:: json

        {
            "app": 18,
            "body": "It stopped working. All dueces, now.",
            "rating": 2
        }

    :status 202: successfully updated.
    :status 400: invalid submission.


_`Delete`
=========

.. http:delete:: /api/v1/apps/rating/(int:rating_id)/

    Delete a rating from the Marketplace using its `resource_uri` from the
    `List`_.

    .. note:: Authentication required.

    **Response**:

    :status 204: successfully deleted.
    :status 403: the user cannot delete the rating. A user may only delete a
        rating if they are the original rating author, if they are an editor
        that is not an author of the app, or if they are in a group with
        Users:Edit or Addons:Edit privileges.


Flagging as spam
================

.. http:post:: /api/v1/apps/rating/(int:rating_id)/flag/

    Flag a rating as spam.

    .. note:: Authentication required.

    **Request**:

    .. code-block:: json

        {
            "flag": "review_flag_reason_spam"
        }
