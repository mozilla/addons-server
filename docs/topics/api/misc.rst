.. _misc:

======================
Miscellaneous API
======================

Account
=======

.. note:: Requires authentication.

To get data on the currently logged in user::

    GET /api/account/mine/

Returns account information::

    {"resource_uri": "/api/apps/account/1/",
     "display_name": "Nice person",
     "installed': [
        "/api/apps/3/",
     ]}

The same information is also accessible at the canoncial `resource_uri`::

    GET /api/account/1/

The `/api/account/mine/` URL is provided as a convenience for users who don't
know their full URL ahead of time.

Categories
==========

To find a list of categories available on the marketplace::

    GET /api/apps/category/

Returns the list of categories::

    {"meta": {"limit": 20, "next": null...},
     "objects": [{"id": 1, "name": "App"...]}
    }

Use the `id` of the category in your app updating.
