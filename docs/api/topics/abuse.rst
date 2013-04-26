.. _abuse:

=====
Abuse
=====

Abusive apps and users may be reported to Marketplace staff.

    .. note:: Authentication is optional for abuse reports.

    .. note:: These endpoints are rate-limited at 30 requests per hour per user.


Report An Abusive App
=====================

.. http:post:: /api/v1/abuse/app/

    Report an abusive app to Marketplace staff.

    **Request**

    :param text: a textual description of the abuse
    :param app: the app id or slug of the app being reported

    .. code-block:: json

        {
            "sprout": "potato",
            "text": "There is a problem with this app.",
            "app": 2
        }

    This endpoint uses `PotatoCaptcha`, so there must be a field named `sprout`
    with the value `potato` and cannot be a field named `tuber` with a truthy
    value.

    **Response**

    .. code-block:: json

        {
            "reporter": null,
            "text": "There is a problem with this app.",
            "app": {
                "id": 2,
                "name": "cvan's app",
                "...": "more info"
            }
        }

    :status 201: successfully submitted.
    :status 400: submission error.
    :status 429: exceeded rate limit.


Report An Abusive User
======================

.. http:post:: /api/v1/abuse/user/

    Report an abusive user to Marketplace staff.

    **Request**

    :param text: a textual description of the abuse
    :param user: the primary key of the user being reported

    .. code-block:: json

        {
            "sprout": "potato",
            "text": "There is a problem with this user",
            "user": 27
        }

    This endpoint uses `PotatoCaptcha`, so there must be a field named `sprout`
    with the value `potato` and cannot be a field named `tuber` with a truthy
    value.

    **Response**

    .. code-block:: json

        {
            "reporter": null,
            "text": "There is a problem with this user.",
            "user": {
                "display_name": "cvan",
                "resource_uri": "/api/v1/account/settings/27/"
            }
        }

    :status 201: successfully submitted.
    :status 400: submission error.
    :status 429: exceeded rate limit.
