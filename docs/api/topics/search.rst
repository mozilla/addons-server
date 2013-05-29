.. _search:

======
Search
======

This API allows search for apps by various properties.

.. _search-api:

Search
======

.. http:get:: /api/v1/apps/search/

    **Request**

    :param optional q: The query string to search for.
    :param optional cat: The category slug or ID to filter by. Use the
        category API to find the ids of the categories.
    :param optional device: Filters by supported device. One of 'desktop',
        'mobile', 'tablet', or 'firefoxos'.
    :param optional premium_types: Filters by whether the app is free or
        premium or has in-app purchasing. Any of 'free', 'free-inapp',
        'premium', 'premium-inapp', or 'other'.
    :param optional type: Filters by type of add-on. One of 'app' or
        'theme'.
    :param optional app_type: Filters by type of web app. One of 'hosted' or
        'packaged'.
    :param optional sort: The field to sort by. One of 'downloads', 'rating',
        'price', 'created'. Sorts by relevance by default.

    The following parameters requires an OAuth token by a user with App
    Reviewer privileges:

    :param optional status: Filters by app status. Default is 'public'. One
        of 'pending', 'public', 'disabled', 'rejected', 'waiting'.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of
    :ref:`apps <app-response-label>`, with the following additional
    fields:

    .. code-block:: json

        {
            "absolute_url": http://server.local/app/my-app/",
        }

    :status 200: successfully completed.
    :status 401: if attempting to filter by status, you do not have that role.

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
