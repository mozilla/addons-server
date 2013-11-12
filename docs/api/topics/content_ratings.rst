.. _content_ratings:

===============
Content Ratings
===============

API for IARC (International Age Rating Coalition) app content ratings.

Content Rating
==============

.. http:get:: /api/v1/apps/app/(int:id|string:app_slug)/content-ratings

    Returns the list of content ratings of an app.

    **Request**

    :param since: filter only for content ratings modified after the datetime.
    :type since: datetime (e.g. `2013-12-25 14:12:36`)

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of content ratings.
    :type objects: array

    :status 200: successfully completed.
    :status 404: not found.

    Example:

    .. code-block:: json

        {
            "objects": [
                {
                    "id": 34,
                    "created": "2013-06-14T11:54:24",
                    "modified": "2013-06-24T22:01:37",
                    "body_name": "ESRB",
                    "body_slug": "esrb",
                    "name": "Everyone 10+",
                    "slug": "10",
                    "description": "Not recommended for users younger than 10 years of age"
                },
                {
                    "id": 35,
                    "created": "2013-06-14T11:54:24",
                    "modified": "2013-06-24T22:01:37",
                    "body_name": "PEGI",
                    "body_slug": "pegi",
                    "name": "3+",
                    "slug": "3",
                    "description": "Not recommended for users younger than 3 years of age"
                },
                ...
            ]
        }
