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

    :query string q: The search query.
    :query string app: Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string platform: Filter by :ref:`add-on platform <addon-detail-platform>` availability.
    :query string type: Filter by :ref:`add-on type <addon-detail-type>`.
    :query string sort: The sort parameter. The available parameters are documented in the :ref:`table below <addon-search-sort>`.
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

    You can combine multiple parameters by separating them with a comma.
    For instance, to sort search results by downloads and then by creation
    date, use `sort=downloads,created`.

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
    :>json array authors: Array holding information about the authors for the add-on.
    :>json int authors[].id: The id for an author.
    :>json string authors[].name: The name for an author.
    :>json string authors[].url: The link to the profile page for an author.
    :>json int average_daily_users: The average number of users for the add-on per day.
    :>json object compatibility: Object detailing the add-on :ref:`add-on application <addon-detail-application>` and version compatibility.
    :>json object compatibility[app_name].max: Maximum version of the corresponding app the add-on is compatible with.
    :>json object compatibility[app_name].min: Minimum version of the corresponding app the add-on is compatible with.
    :>json object current_version: Object holding the current :ref:`version <version-detail-object>` of the add-on. For performance reasons the ``license`` and ``release_notes`` fields are omitted.
    :>json string default_locale: The add-on default locale for translations.
    :>json string|object|null description: The add-on description (:ref:`translated field <api-overview-translations>`).
    :>json string edit_url: The URL to the developer edit page for the add-on.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json string|object|null homepage: The add-on homepage (:ref:`translated field <api-overview-translations>`).
    :>json string icon_url: The URL to icon for the add-on (including a cachebusting query string).
    :>json boolean is_disabled: Whether the add-on is disabled or not.
    :>json boolean is_experimental: Whether the add-on has been marked by the developer as experimental or not.
    :>json boolean is_listed: Whether the add-on is listed or not.
    :>json boolean is_source_public: Whether the add-on source is publicly viewable or not.
    :>json string|object|null name: The add-on name (:ref:`translated field <api-overview-translations>`).
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json array previews: Array holding information about the previews for the add-on.
    :>json int previews[].id: The id for a preview.
    :>json string|object|null previews[].caption: The caption describing a preview (:ref:`translated field <api-overview-translations>`).
    :>json string previews[].image_url: The URL (including a cachebusting query string) to the preview image.
    :>json string previews[].thumbnail_url: The URL (including a cachebusting query string) to the preview image thumbnail.
    :>json boolean public_stats: Boolean indicating whether the add-on stats are public or not.
    :>json object ratings: Object holding ratings summary information about the add-on.
    :>json int ratings.count: The number of user ratings for the add-on.
    :>json float ratings.average: The average user rating for the add-on.
    :>json string review_url: The URL to the review page for the add-on.
    :>json string slug: The add-on slug.
    :>json string status: The :ref:`add-on status <addon-detail-status>`.
    :>json string|object|null summary: The add-on summary (:ref:`translated field <api-overview-translations>`).
    :>json string|object|null support_email: The add-on support email (:ref:`translated field <api-overview-translations>`).
    :>json string|object|null support_url: The add-on support URL (:ref:`translated field <api-overview-translations>`).
    :>json array tags: List containing the text of the tags set on the add-on.
    :>json object theme_data: Object holding `lightweight theme (Persona) <https://developer.mozilla.org/en-US/Add-ons/Themes/Lightweight_themes>`_ data. Only present for themes (Persona).
    :>json string type: The :ref:`add-on type <addon-detail-type>`.
    :>json string url: The (absolute) add-on detail URL.
    :>json int weekly_downloads: The number of downloads for the add-on per week.


.. _addon-detail-status:

    Possible values for the ``status`` field / parameter:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
              beta  Beta (Valid for files only)
              lite  Preliminarily Reviewed
            public  Fully Reviewed
           deleted  Deleted
           pending  Pending approval (Valid for themes only)
          disabled  Disabled by Mozilla
          rejected  Rejected (Valid for themes only)
         nominated  Awaiting Full Review
        incomplete  Incomplete
        unreviewed  Awaiting Preliminary Review
    lite-nominated  Preliminarily Reviewed and Awaiting Full Review
    review-pending  Flagged for further review (Valid for themes only)
    ==============  ==========================================================


.. _addon-detail-application:

    Possible values for the keys in the ``compatibility`` field, as well as the
    ``app`` parameter in the search API:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
           android  Firefox for Android
           firefox  Firefox
         seamonkey  SeaMonkey
       thunderbird  Thunderbird
    ==============  ==========================================================

.. _addon-detail-platform:

    Possible values for the ``current_version.files[].platform`` field:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
               all  All
               mac  Mac
             linux  Linux
           android  Android
           windows  Windows
    ==============  ==========================================================

.. _addon-detail-type:

    Possible values for the ``type`` field / parameter:

    .. note::

        For backwards-compatibility reasons, the value for Theme is ``persona``.
        ``theme`` refers to a Complete Theme.

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
             theme  Complete Theme
            search  Search Engine
           persona  Theme
          language  Language Pack (Application)
         extension  Extension
        dictionary  Dictionary
    ==============  ==========================================================

-------------
Versions List
-------------

.. _version-list:

This endpoint allows you to list all versions belonging to a specific add-on.

.. http:get:: /api/v3/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/

    .. note::
        Unlisted or non-public add-ons require authentication and either
        reviewer permissions or a user account listed as a developer of the
        add-on.

    :query string filter: The :ref:`filter <version-filtering-param>` to apply.
    :>json int count: The number of versions for this add-on.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`versions <version-detail-object>`.

.. _version-filtering-param:

   By default, the version list API will only return versions with valid statuses
   (excluding versions that have incomplete, disabled, deleted, rejected or
   flagged for further review files) - you can change that with the ``filter``
   query parameter, which requires authentication and specific permissions
   depending on the value:

    ================  ========================================================
               Value  Description
    ================  ========================================================
                 all  Show all versions attached to this add-on. Requires
                      either reviewer permissions or a user account listed as
                      a developer of the add-on.
    all_with_deleted  Show all versions attached to this add-on, including
                      deleted ones. Requires admin permissions.
    ================  ========================================================

--------------
Version Detail
--------------

.. _version-detail:

This endpoint allows you to fetch a single version belonging to a specific add-on.

.. http:get:: /api/v3/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id)/

    .. _version-detail-object:

    :>json int id: The version id.
    :>json string edit_url: The URL to the developer edit page for the version.
    :>json array files: Array holding information about the files for the version.
    :>json int files[].id: The id for a file.
    :>json string files[].created: The creation date for a file.
    :>json string files[].hash: The hash for a file.
    :>json string files[].platform: The :ref:`platform <addon-detail-platform>` for a file.
    :>json int files[].id: The size for a file, in bytes.
    :>json int files[].status: The :ref:`status <addon-detail-status>` for a file.
    :>json string files[].url: The (absolute) URL to download a file.
    :>json object license: Object holding information about the license for the version.
    :>json string|object|null license.name: The name of the license (:ref:`translated field <api-overview-translations>`).
    :>json string|object|null license.text: The text of the license (:ref:`translated field <api-overview-translations>`).
    :>json string|null license.url: The URL of the full text of license.
    :>json string|object|null release_notes: The release notes for this version (:ref:`translated field <api-overview-translations>`).
    :>json string reviewed: The date the version was reviewed at.
    :>json string version: The version number string for the version.


---------------------
Feature Compatibility
---------------------

.. _addon-feature-compatibility:

This endpoint allows you to fetch feature compatibility information for a
a specific add-on by id, slug or guid.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/feature_compatibility/

    .. note::
        Unlisted or non-public add-ons require authentication and either
        reviewer permissions or a user account listed as a developer of the
        add-on.

    :>json int e10s: The add-on e10s compatibility. Can be one of the following:

    =======================  ==========================================================
                      Value  Description
    =======================  ==========================================================
                 compatible  multiprocessCompatible marked as true in the install.rdf.
    compatible-webextension  A WebExtension, so compatible.
               incompatible  multiprocessCompatible marked as false in the install.rdf.
                    unknown  multiprocessCompatible has not been set.
    =======================  ==========================================================
