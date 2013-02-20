.. _misc:

======================
Miscellaneous API
======================

These APIs are not directly about updating Apps.

Categories
==========

To find a list of categories available on the marketplace::

        GET /api/apps/category/

Returns the list of categories::

        {"meta":
            {"limit": 20, "next": null, "offset": 0,
             "previous": null, "total_count": 1},
         "objects":
            [{"id": 1, "name": "Webapp",
              "resource_uri": "/api/apps/category/1/",
              "slug": "webapp"}]
        }

Use the `id` of the category in your app updating.
