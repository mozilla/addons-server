=======
Add-ons
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning.

    At the moment these APIs don't yet require authentication and therefore
    are limited to listed public add-ons.

------
Search
------

.. _addon-search:

This endpoint allows you to search through public add-ons.

.. http:get:: /api/v3/addons/search/

    :param string q: The search query.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail>`.

------
Detail
------

.. _addon-detail:

This endpoint allows you to fetch a specific add-on by id, slug or guid.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/

    :>json int id: The add-on id on AMO.
    :>json object current_version: Object holding information about the add-on version served by AMO currently.
    :>json int current_version.id: The id for that version.
    :>json string current_version.reviewed: The date that version was reviewed at.
    :>json string current_version.version: The version number string for that version.
    :>json array current_version.files: Array holding information about the files for that version.
    :>json int current_version.files[].id: The id for a file.
    :>json string current_version.files[].created: The creation date for a file.
    :>json string current_version.files[].hash: The hash for a file.
    :>json string current_version.files[].platform: The platform for one a file, in human-readable form.
    :>json int current_version.files[].id: The size for a file, in bytes.
    :>json string current_version.files[].url: The (absolute) URL to download a file.
    :>json string default_locale: The add-on default locale for translations.
    :>json string|object|null description: The add-on description.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json string|object|null homepage: The add-on homepage.
    :>json string|object|null name: The add-on name.
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json boolean public_stats: Boolean indicating whether the add-on stats are public or not.
    :>json string slug: The add-on slug.
    :>json string status: The add-on status, in human-readable form.
    :>json string|object|null summary: The add-on summary.
    :>json string|object|null support_email: The add-on support email.
    :>json string|object|null support_url: The add-on support URL.
    :>json array tags: List containing the text of the tags set on the add-on.
    :>json string type: The add-on type, in human-readable form.
    :>json string url: The (absolute) add-on detail URL.
