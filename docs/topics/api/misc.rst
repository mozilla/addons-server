.. _misc:

======================
Miscellaneous API
======================


Home page and featured apps
===========================

.. http:get:: /api/v1/home/page/

    The home page of the Marketplace which is a list of featured apps and
    categories.

    **Request**:

    :param dev: the device requesting the homepage, results will be tailored to the device which will be one of: `firefoxos` (Firefox OS), `desktop`, `android` (mobile).

    This is not a standard listing page and **does not** accept the standard
    listing query parameters.

    **Response**:

    :param categories: A list of :ref:`categories <category-response-label>`.
    :param featured: A list of :ref:`apps <app-response-label>`.

.. http:get:: /api/v1/home/featured/

    A list of the featured apps on the Marketplace.

    **Request**

    :param dev: The device requesting the homepage, results will be tailored to the device which will be one of: `firefoxos` (Firefox OS), `desktop`, `android` (mobile).
    :param category: The id or slug of the category to filter on.

    Plus standard :ref:`list-query-params-label`.

    Region is inferred from the request.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.

    :status 200: successfully completed.

Account
=======

The account API, makes use of the term `mine`. This is an explicit variable to
lookup the logged in user account id.

.. http:get:: /api/v1/account/settings/mine/

    Returns data on the currently logged in user.

    .. note:: Requires authentication.

    **Response**

    .. code-block:: json

        {
            "resource_uri": "/api/v1/account/settings/1/",
            "display_name": "Nice person",
        }

The same information is also accessible at the canoncial `resource_uri`
`/api/v1/account/settings/1/`.

To update account information:

.. http:patch:: /api/v1/account/settings/mine/

    **Request**

    :param display_name: the displayed name for this user.

    **Response**

    No content is returned in the response.

    :status 201: successfully completed.

Fields that can be updated:

* *display_name*

.. http:get:: /api/v1/account/installed/mine/

    Returns a list of the installed apps for the currently logged in user. This
    ignores any reviewer or developer installed apps.

    .. note:: Requires authentication.

    **Request**

    The standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.
    :status 200: sucessfully completed.

Categories
==========

.. http:get:: /api/v1/apps/category/

    Returns a list of categories available on the marketplace.

    **Response**


    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`categories <category-response-label>`.
    :status 200: successfully completed.


.. _category-response-label:

.. http:get:: /api/v1/apps/category/<id>/

    Returns a category.

    **Request**

    Standard :ref:`list-query-params-label`.

    **Response**

    .. code-block:: json

        {
            "id": "1",
            "name": "Games",
            "resource_uri": "/api/v1/apps/category/1/",
            "slug": "games"
        }


Feedback
========

.. http:post:: /api/v1/account/feedback/

    Submit feedback to the Marketplace.

    .. note:: Authentication is optional.

    .. note:: This endpoint is rate-limited at 30 requests per hour per user.

    **Request**

    :param chromeless: (optional) "Yes" or "No", indicating whether the user
                       agent sending the feedback is chromeless.
    :param feedback: (required) the text of the feedback.
    :param from_url: (optional) the URL from which the feedback was sent.
    :param platform: (optional) a description of the platform from which the
                     feedback is being sent.

    .. code-block:: json

        {
            "chromeless": "No",
            "feedback": "Here's what I really think.",
            "platform": "Desktop",
            "from_url": "/feedback",
            "sprout": "potato"
        }

    This form uses `PotatoCaptcha`, so there must be a field named `sprout` with
    the value `potato` and cannot be a field named `tuber` with a truthy value.

    **Response**

    .. code-block:: json

        {
            "chromeless": "No",
            "feedback": "Here's what I really think.",
            "from_url": "/feedback",
            "platform": "Desktop",
            "user": null,
        }

    :status 201: successfully completed.
    :status 429: exceeded rate limit.


Abuse
=====


Abusive apps and users may be reported to Marketplace staff.

    .. note:: Authentication is optional for abuse reports.

    .. note:: These endpoints are rate-limited at 30 requests per hour per user.


Report An Abusive App
---------------------

.. http:post:: /api/v1/abuse/app/

    Report an abusive app to Marketplace staff.

    **Request**

    :param text: a textual description of the abuse
    :param app: the primary key of the app being reported

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
----------------------

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
                "id": "27",
                "username": "cvan"
            }
        }

    :status 201: successfully submitted.
    :status 400: submission error.
    :status 429: exceeded rate limit.
