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

.. http:get:: /api/v1/account/settings/mine/

    Returns data on the currently logged in user.

    .. note:: Requires authentication.

    **Response**

    .. code-block:: json

        {
            "resource_uri": "/api/v1/account/settings/1/",
            "display_name": "Nice person",
            "installed": [
                "/api/v1/apps/3/"
            ]
        }

The same information is also accessible at the canoncial `resource_uri`
`/api/v1/account/settings/1/`. The `/api/v1/account/mine/` URL is provided as
a convenience for users who don't know their full URL ahead of time.

To update account information:

.. http:patch:: /api/v1/account/settings/mine/

    **Request**

    :param display_name: the displayed name for this user.

    **Response**

    No content is returned in the response.

    :status 201: successfully completed.

Fields that can be updated:

* *display_name*

Fields that are read only:

* *installed*

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

    **Request**

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


Abuse
=====


Abusive apps and users may be reported to Marketplace staff.

    .. note:: Authentication is optional for abuse reports.


Report An Abusive App
---------------------

.. http:post:: /api/abuse/app/

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


Report An Abusive User
----------------------

.. http:post:: /api/abuse/user/

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
