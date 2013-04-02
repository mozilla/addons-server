.. _misc:

======================
Miscellaneous API
======================


Home page
=========

The home page of the Marketplace which is a list of featured apps and
categories.

.. http:get:: /api/v1/home/page/

    **Request**:

    .. sourcecode:: http

        GET /api/v1/home/page/


    :param dev: the device requesting the homepage, results will be tailored to the device which will be one of: `firefoxos` (Firefox OS), `desktop`, `android` (mobile).

    **Response**:

    .. sourcecode:: http

        {"categories": [
            {"id": "99",
             "name": "Lifestyle"...}
         ],
         "featured": [{
            {"slug": "cool-app",
             "name": "Cool app"...}
         ]
        }

Featured apps
=============

A list of the featured apps on the Marketplace.

.. http:get:: /api/v1/home/featured/

    **Request**

    .. sourcecode:: http

        GET /api/v1/home/featured/

    :param dev: the device requesting the homepage, results will be tailored to the device which will be one of: `firefoxos` (Firefox OS), `desktop`, `android` (mobile).
    :param category: the id of the category to filter on.
    :param limit: the number of responses.

    **Response**

    .. sourcecode:: http

        {"meta": {"limit": 20, ...},
         "objects": [
            {"app_type": "hosted"...}
         ]
        }

Region is inferred from the request.

Account
=======

.. note:: Requires authentication.

To get data on the currently logged in user::

    GET /api/v1/account/settings/mine/

Returns account information::

    {"resource_uri": "/api/v1/account/settings/1/",
     "display_name": "Nice person",
     "installed': [
        "/api/v1/apps/3/",
     ]}

The same information is also accessible at the canoncial `resource_uri`::

    GET /api/v1/account/settings/1/

The `/api/v1/account/mine/` URL is provided as a convenience for users who don't
know their full URL ahead of time.

To update account information::

    PATCH /api/v1/account/settings/mine/
    {"display_name": "Nicer person"}

Or::

    PUT /api/v1/account/settings/mine/
    {"display_name": "Nicer person"}


Fields that can be updated:

* *display_name*

Fields that are read only:

* *installed*

Categories
==========

To find a list of categories available on the marketplace::

    GET /api/v1/apps/category/

Returns the list of categories::

    {
    "meta": {
        "limit": 20,
        "next": null,
        "offset": 0,
        "previous": null,
        "total_count": 16
    },
    "objects": [
        {
            "id": "1",
            "name": "Games",
            "resource_uri": "/api/v1/apps/category/1/",
            "slug": "games"
        },
        ...
    }

Use the `id` of the category in your app updating.


Feedback
========

.. http:post:: /api/v1/account/feedback/

    Submit feedback to the Marketplace.

    .. note:: Authentication is optional.

    **Request**

    The request body should include a JSON representation of the feedback::

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

    Returns 201 on successful submission, with the response body containing a
    serialization of the feedback data::

        {
            "chromeless": "No",
            "feedback": "Here's what I really think.",
            "from_url": "/feedback",
            "platform": "Desktop",
            "user": null,
        }
