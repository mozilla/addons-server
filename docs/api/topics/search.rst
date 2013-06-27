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
    :type q: string
    :param optional cat: The category slug or ID to filter by. Use the
        category API to find the ids of the categories.
    :type cat: int|string
    :param optional device: Filters by supported device. One of 'desktop',
        'mobile', 'tablet', or 'firefoxos'.
    :type device: string
    :param optional premium_types: Filters by whether the app is free or
        premium or has in-app purchasing. Any of 'free', 'free-inapp',
        'premium', 'premium-inapp', or 'other'.
    :type premium_types: string
    :param optional type: Filters by type of add-on. One of 'app' or
        'theme'.
    :type type: string
    :param optional app_type: Filters by type of web app. One of 'hosted' or
        'packaged'.
    :type app_type: string
    :param optional manifest_url: Filters by manifest URL. Requires an
        exact match and should only return a single result if a match is
        found.
    :type manifest_url: string
    :param optional sort: The fields to sort by. One or more of 'downloads', 'rating',
        'price', 'created', separated by commas. Sorts by relevance by default.
    :type sort: string

    The following parameters requires an OAuth token by a user with App
    Reviewer privileges:

    :param optional status: Filters by app status. Default is 'public'. One
        of 'pending', 'public', 'disabled', 'rejected', 'waiting'.
    :type status: string
    :param optional is_privileged: Filters by whether the latest version of the
        app is privileged or not.
    :type is_privileged: boolean

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of
        :ref:`apps <app-response-label>`, with the following additional
        fields:
    :type objects: array


    .. code-block:: json

        {
            "absolute_url": http://server.local/app/my-app/",
        }

    :status 200: successfully completed.
    :status 401: if attempting to filter by status, you do not have that role.

Featured App Listing
====================

.. http:get::  /api/v1/fireplace/search/featured/

    **Request**

    Accepts the same parameters and returns the same objects as the
    normal search interface: :ref:`search-api`.  Includes 'featured'
    list of apps, listing featured apps for the requested category, if
    any. When no category is specified, frontpage featured apps are
    listed.

    **Response**:

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of
        :ref:`apps <app-response-label>` satisfying the search parameters.
    :type objects: array
    :param featured: A list of :ref:`apps <app-response-label>` featured
        for the requested category, if any
    :type featured: array
    :status 200: successfully completed.
