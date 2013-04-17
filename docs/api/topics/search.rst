.. _search:

======
Search
======

This API allows search for apps by various properties.

.. _search-api:

Search
======

To get a list of apps from the Marketplace::

    GET /api/v1/apps/search/

The API accepts various query string parameters to filter or sort by
described below:

* `q` (optional): The query string to search for.
* `cat` (optional): The category slug or ID to filter by. Use the
  category API to find the ids of the categories.
* `device` (optional): Filters by supported device. One of 'desktop',
  'mobile', 'tablet', or 'gaia'.
* `premium_types` (optional): Filters by whether the app is free or
  premium or has in-app purchasing. Any of 'free', 'free-inapp',
  'premium', 'premium-inapp', or 'other'.
* `addon_type` (optional): Filters by type of add-on. One of 'app' or
  'persona'.
* `app_type` (optional): Filters by type of web app. One of 'hosted' or
  'packaged'.
* `sort` (optional): The field to sort by. One of 'downloads', 'rating',
  'price', 'created'. Sorts by relevance by default.

The following parameters requires an OAuth token by a user with App
Reviewer privileges:

* `status` (optional): Filters by app status. Default is 'public'. One of
  'pending', 'public', 'disabled', 'rejected', 'waiting'.

The API returns a list of the apps sorted by relevance (default) or
`sort`::

        {"meta": {},
         "objects": [{
            "id": "26",
            "absolute_url": "http://../app/marble-run/",
            "categories": [9, 10],
            "description": "...",
            "device_types": [...],
            "icon_url_128": "...",
            "name": "Marble Run",
            "premium_type": "free",
            "resource_uri": null,
            "slug": "marble-run"
         }, ...]
        }


Featured App Listing
===================================

.. http:get::  /api/v1/apps/search/featured/

    **Request**

    Accepts the same parameters and returns the same objects as the
    normal search interface: :ref:`search-api`.  Includes 'featured'
    list of apps, listing featured apps for the requested category, if
    any. When no category is specified, frontpage featured apps are
    listed.

    **Response**:

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>` satisfying the search parameters.
    :param featured: A list of :ref:`apps <app-response-label>` featured for the requested category, if any
    :status 200: successfully completed..
