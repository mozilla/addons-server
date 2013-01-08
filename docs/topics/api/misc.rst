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
              "resource_uri": "/api/apps/category/1/"}]
        }

Use the `id` of the category in your app updating.

Search
======

To find a list of apps in a category on the marketplace::

        GET /api/apps/search/

Returns a list of the apps sorted by relevance::

        {"meta": {},
         "objects":
            [{"absolute_url": "http://../app/marble-run-1/",
              "premium_type": 3, "slug": "marble-run-1", id="26",
              "icon_url": "http://../addon_icons/0/26-32.png",
              "resource_uri": null
             }
         ...

Arguments:

* `cat` (optional): use the category API to find the ids of the categories
* `sort` (optional): one of 'downloads', 'rating', 'price', 'created'

Example, to specify a category sorted by rating::

        GET /api/apps/search/?cat=1&sort=rating

.. _`MDN`: https://developer.mozilla.org
.. _`Marketplace representative`: marketplace-team@mozilla.org
.. _`django-tastypie`: https://github.com/toastdriven/django-tastypie
.. _`APIs for Add-ons`: https://developer.mozilla.org/en/addons.mozilla.org_%28AMO%29_API_Developers%27_Guide
.. _`example marketplace client`: https://github.com/mozilla/Marketplace.Python
