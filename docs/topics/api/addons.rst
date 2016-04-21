=======
Add-ons
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

------
Search
------

.. _addon-search:

This endpoint allows you to search through public add-ons.

.. http:get:: /api/v3/addons/search/

    :param string q: The search query.
    :param string sort: The sort parameter. The available parameters are documented in the :ref:`table below <addon-search-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`.

.. _addon-search-sort:

    Available sorting parameters:

    ==============  ==========================================================
         Parameter  Description
    ==============  ==========================================================
           created  Creation date, descending
         downloads  Number of weekly downloads, descending
           hotness  Hotness (average number of users progression), descending.
            rating  Bayesian rating, descending.
           updated  Last updated date, descending
             users  Average number of daily users, descending.
    ==============  ==========================================================

    The default is to sort by number of weekly downloads, descending.

    You can combine multiple parameters by separating multiple parameters with
    a comma. For instance, to sort search results by downloads and then by
    creation date, use `sort=downloads,created`. 

------
Detail
------

.. _addon-detail:

This endpoint allows you to fetch a specific add-on by id, slug or guid.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/

    .. note::
        Unlisted or non-public add-ons require authentication and either
        reviewer permissions or a user account listed as a developer of the
        add-on.

    .. _addon-detail-object:

    :>json int id: The add-on id on AMO.
    :>json object current_version: Object holding information about the add-on version served by AMO currently.
    :>json int current_version.id: The id for that version.
    :>json string current_version.reviewed: The date that version was reviewed at.
    :>json string current_version.version: The version number string for that version.
    :>json string current_version.edit_url: The URL to the developer edit page for this version.
    :>json array current_version.files: Array holding information about the files for that version.
    :>json int current_version.files[].id: The id for a file.
    :>json string current_version.files[].created: The creation date for a file.
    :>json string current_version.files[].hash: The hash for a file.
    :>json string current_version.files[].platform: The platform for one a file, in human-readable form.
    :>json int current_version.files[].id: The size for a file, in bytes.
    :>json string current_version.files[].url: The (absolute) URL to download a file.
    :>json string default_locale: The add-on default locale for translations.
    :>json string|object|null description: The add-on description.
    :>json string edit_url: The URL to the developer edit page for this add-on.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json string|object|null homepage: The add-on homepage.
    :>json string|object|null name: The add-on name.
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json boolean public_stats: Boolean indicating whether the add-on stats are public or not.
    :>json string review_url: The URL to the review page for this add-on.
    :>json string slug: The add-on slug.
    :>json string status: The add-on status, in human-readable form.
    :>json string|object|null summary: The add-on summary.
    :>json string|object|null support_email: The add-on support email.
    :>json string|object|null support_url: The add-on support URL.
    :>json array tags: List containing the text of the tags set on the add-on.
    :>json string type: The add-on type, in human-readable form.
    :>json string url: The (absolute) add-on detail URL.
