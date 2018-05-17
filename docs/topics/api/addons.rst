=======
Add-ons
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

--------
Featured
--------

.. _addon-featured:

This endpoint allows you to list featured add-ons matching some parameters.
Results are sorted randomly and therefore, the standard pagination parameters
are not accepted. The query parameter ``page_size`` is allowed but only serves
to customize the number of results returned, clients can not request a specific
page.

.. http:get:: /api/v4/addons/featured/

    :query string app: **Required**. Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string category: Filter by :ref:`category slug <category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string lang: Request add-ons featured for this specific language to be returned alongside add-ons featured globally. Also activate translations for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string type: Filter by :ref:`add-on type <addon-detail-type>`.
    :query int page_size: Maximum number of results to return. Defaults to 25.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`.

------
Search
------

.. _addon-search:

This endpoint allows you to search through public add-ons.

.. http:get:: /api/v4/addons/search/

    :query string q: The search query. The maximum length allowed is 100 characters.
    :query string app: Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string author: Filter by exact author username. Multiple author names can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string category: Filter by :ref:`category slug <category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string exclude_addons: Exclude add-ons by ``slug`` or ``id``. Multiple add-ons can be specified, separated by comma(s).
    :query boolean featured: Filter to only featured add-ons.  Only ``featured=true`` is supported.
        If ``app`` is provided as a parameter then only featured collections targeted to that application are taken into account.
        If ``lang`` is provided then only featured collections targeted to that language, (and collections for all languages), are taken into account. Both ``app`` and ``lang`` can be provided to filter to addons that are featured in collections that application and for that language, (and for all languages).
    :query string guid: Filter by exact add-on guid. Multiple guids can be specified, separated by comma(s), in which case any add-ons matching any of the guids will be returned.  As guids are unique there should be at most one add-on result per guid specified.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :query string platform: Filter by :ref:`add-on platform <addon-detail-platform>` availability.
    :query string tag: Filter by exact tag name. Multiple tag names can be specified, separated by comma(s), in which case add-ons containing *all* specified tags are returned.
    :query string type: Filter by :ref:`add-on type <addon-detail-type>`.
    :query string sort: The sort parameter. The available parameters are documented in the :ref:`table below <addon-search-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`. As described below, the following fields are omitted for performance reasons: ``release_notes`` and ``license`` fields on ``current_version`` as well as ``picture_url`` from ``authors``.

.. _addon-search-sort:

    Available sorting parameters:

    ==============  ==========================================================
         Parameter  Description
    ==============  ==========================================================
           created  Creation date, descending.
         downloads  Number of weekly downloads, descending.
           hotness  Hotness (average number of users progression), descending.
            random  Random ordering. Only available when no search query is
                    passed and when filtering to only return featured add-ons.
            rating  Bayesian rating, descending.
         relevance  Search query relevance, descending.
           updated  Last updated date, descending.
             users  Average number of daily users, descending.
    ==============  ==========================================================

    The default is to sort by relevance if a search query (``q``) is present,
    otherwise sort by number of weekly downloads, descending.

    You can combine multiple parameters by separating them with a comma.
    For instance, to sort search results by downloads and then by creation
    date, use ``sort=downloads,created``. The only exception is the ``random``
    sort parameter, which is only available alone.


------------
Autocomplete
------------

.. _addon-autocomplete:

Similar to :ref:`add-ons search endpoint <addon-search>` above, this endpoint
allows you to search through public add-ons. Because it's meant as a backend
for autocomplete though, there are a couple key differences:

  - No pagination is supported. There are no ``next``, ``prev`` or ``count``
    fields, and passing ``page_size`` or ``page`` has no effect, a maximum of 10
    results will be returned at all times.
  - Only a subset of fields are returned.

.. http:get:: /api/v4/addons/autocomplete/

    :query string q: The search query.
    :query string app: Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string author: Filter by exact author username.
    :query string category: Filter by :ref:`category slug <category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string platform: Filter by :ref:`add-on platform <addon-detail-platform>` availability.
    :query string tag: Filter by exact tag name. Multiple tag names can be specified, separated by comma(s).
    :query string type: Filter by :ref:`add-on type <addon-detail-type>`.
    :query string sort: The sort parameter. The available parameters are documented in the :ref:`table below <addon-search-sort>`.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`. Only the ``id``, ``icon_url``, ``name`` and ``url`` fields are supported though.


------
Detail
------

.. _addon-detail:

This endpoint allows you to fetch a specific add-on by id, slug or guid.

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both
        authentication and reviewer permissions or an account listed as a
        developer of the add-on.

        A 401 or 403 error response will be returned when clients don't meet
        those requirements. Those responses will contain the following
        properties:

            * ``detail``: string containing a message about the error.
            * ``is_disabled_by_developer``: boolean set to ``true`` when the add-on has been voluntarily disabled by its developer.
            * ``is_disabled_by_mozilla``: boolean set to ``true`` when the add-on has been disabled by Mozilla.

.. http:get:: /api/v4/addons/addon/(int:id|string:slug|string:guid)/

    .. _addon-detail-object:

    :query string lang: Activate translations in the specific language for that query. (See :ref:`Translated Fields <api-overview-translations>`)
    :query string wrap_outgoing_links: If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json int id: The add-on id on AMO.
    :>json array authors: Array holding information about the authors for the add-on.
    :>json int authors[].id: The id for an author.
    :>json string authors[].name: The name for an author.
    :>json string authors[].url: The link to the profile page for an author.
    :>json string authors[].username: The username for an author.
    :>json string authors[].picture_url: URL to a photo of the user, or `/static/img/anon_user.png` if not set. For performance reasons this field is omitted from the search endpoint.
    :>json int average_daily_users: The average number of users for the add-on (updated daily).
    :>json object categories: Object holding the categories the add-on belongs to.
    :>json array categories[app_name]: Array holding the :ref:`category slugs <category-list>` the add-on belongs to for a given :ref:`add-on application <addon-detail-application>`. (Combine with the add-on ``type`` to determine the name of the category).
    :>json string|null contributions_url: URL to the (external) webpage where the addon's authors collect monetary contributions, if set.
    :>json object current_version: Object holding the current :ref:`version <version-detail-object>` of the add-on. For performance reasons the ``license`` field omits the ``text`` property from the detail endpoint. In addition, ``license`` and ``release_notes`` are omitted entirely from the search endpoint.
    :>json string default_locale: The add-on default locale for translations.
    :>json string|object|null description: The add-on description (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null developer comments: Additional information about the add-on provided by the developer. (See :ref:`translated fields <api-overview-translations>`).
    :>json string edit_url: The URL to the developer edit page for the add-on.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json boolean has_eula: The add-on has an End-User License Agreement that the user needs to agree with before installing (See :ref:`add-on EULA and privacy policy <addon-eula-policy>`).
    :>json boolean has_privacy_policy: The add-on has a Privacy Policy (See :ref:`add-on EULA and privacy policy <addon-eula-policy>`).
    :>json string|object|null homepage: The add-on homepage (See :ref:`translated fields <api-overview-translations>`).
    :>json string icon_url: The URL to icon for the add-on (including a cachebusting query string).
    :>json object icons: An object holding the URLs to an add-ons icon including a cachebusting query string as values and their size as properties. Currently exposes 32 and 64 pixels wide icons.
    :>json boolean is_disabled: Whether the add-on is disabled or not.
    :>json boolean is_experimental: Whether the add-on has been marked by the developer as experimental or not.
    :>json boolean is_featured: The add-on appears in a featured collection.
    :>json boolean is_source_public: Whether the add-on source is publicly viewable or not.
    :>json string|object|null name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json object|null latest_unlisted_version: Object holding the latest unlisted :ref:`version <version-detail-object>` of the add-on. This field is only present if the user has unlisted reviewer permissions, or is listed as a developer of the add-on.
    :>json array previews: Array holding information about the previews for the add-on.
    :>json int previews[].id: The id for a preview.
    :>json string|object|null previews[].caption: The caption describing a preview (See :ref:`translated fields <api-overview-translations>`).
    :>json int previews[].image_size[]: width, height dimensions of of the preview image.
    :>json string previews[].image_url: The URL (including a cachebusting query string) to the preview image.
    :>json int previews[].thumbnail_size[]: width, height dimensions of of the preview image thumbnail.
    :>json string previews[].thumbnail_url: The URL (including a cachebusting query string) to the preview image thumbnail.
    :>json boolean public_stats: Boolean indicating whether the add-on stats are public or not.
    :>json object ratings: Object holding ratings summary information about the add-on.
    :>json int ratings.count: The total number of user ratings for the add-on.
    :>json int ratings.text_count: The number of user ratings with review text for the add-on.
    :>json string ratings_url: The URL to the user ratings list page for the add-on.
    :>json float ratings.average: The average user rating for the add-on.
    :>json float ratings.bayesian_average: The bayesian average user rating for the add-on.
    :>json boolean requires_payment: Does the add-on require payment, non-free services or software, or additional hardware.
    :>json string review_url: The URL to the reviewer review page for the add-on.
    :>json string slug: The add-on slug.
    :>json string status: The :ref:`add-on status <addon-detail-status>`.
    :>json string|object|null summary: The add-on summary (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null support_email: The add-on support email (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null support_url: The add-on support URL (See :ref:`translated fields <api-overview-translations>`).
    :>json array tags: List containing the text of the tags set on the add-on.
    :>json object theme_data: Object holding `lightweight theme (Persona) <https://developer.mozilla.org/en-US/Add-ons/Themes/Lightweight_themes>`_ data. Only present for themes (Persona).
    :>json string type: The :ref:`add-on type <addon-detail-type>`.
    :>json string url: The (absolute) add-on detail URL.
    :>json int weekly_downloads: The number of downloads for the add-on in the last week. Not present for lightweight themes.


.. _addon-detail-status:

    Possible values for the ``status`` field / parameter:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
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

    .. note::
        For possible version values per application, see
        `valid application versions`_.

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


-----------------------------
Add-on and Version Submission
-----------------------------

See :ref:`Uploading a version <upload-version>`.

-------------
Versions List
-------------

.. _version-list:

This endpoint allows you to list all versions belonging to a specific add-on.

.. http:get:: /api/v4/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both:

            * authentication
            * reviewer permissions or an account listed as a developer of the add-on

    :query string filter: The :ref:`filter <version-filtering-param>` to apply.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The number of versions for this add-on.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`versions <version-detail-object>`.

.. _version-filtering-param:

   By default, the version list API will only return public versions
   (excluding versions that have incomplete, disabled, deleted, rejected or
   flagged for further review files) - you can change that with the ``filter``
   query parameter, which may require authentication and specific permissions
   depending on the value:

    ====================  =====================================================
                   Value  Description
    ====================  =====================================================
    all_without_unlisted  Show all listed versions attached to this add-on.
                          Requires either reviewer permissions or a user
                          account listed as a developer of the add-on.
       all_with_unlisted  Show all versions (including unlisted) attached to
                          this add-on. Requires either reviewer permissions or
                          a user account listed as a developer of the add-on.
        all_with_deleted  Show all versions attached to this add-on, including
                          deleted ones. Requires admin permissions.
    ====================  =====================================================

--------------
Version Detail
--------------

.. _version-detail:

This endpoint allows you to fetch a single version belonging to a specific add-on.

.. http:get:: /api/v4/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id)/

    .. _version-detail-object:

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :>json int id: The version id.
    :>json string channel: The version channel, which determines its visibility on the site. Can be either ``unlisted`` or ``listed``.
    :>json object compatibility:
        Object detailing which :ref:`applications <addon-detail-application>` the version is compatible with.
        The exact min/max version numbers in the object correspond to
        `valid application versions`_. Example:

            .. code-block:: json

                {
                  "compatibility": {
                    "android": {
                      "min": "38.0a1",
                      "max": "43.0"
                    },
                    "firefox": {
                      "min": "38.0a1",
                      "max": "43.0"
                    }
                  }
                }

    :>json object compatibility[app_name].max: Maximum version of the corresponding app the version is compatible with. Should only be enforced by clients if ``is_strict_compatibility_enabled`` is ``true``.
    :>json object compatibility[app_name].min: Minimum version of the corresponding app the version is compatible with.
    :>json string edit_url: The URL to the developer edit page for the version.
    :>json array files: Array holding information about the files for the version.
    :>json int files[].id: The id for a file.
    :>json string files[].created: The creation date for a file.
    :>json string files[].hash: The hash for a file.
    :>json string files[].platform: The :ref:`platform <addon-detail-platform>` for a file.
    :>json int files[].id: The size for a file, in bytes.
    :>json boolean files[].is_mozilla_signed_extension: Whether the file was signed with a Mozilla internal certificate or not.
    :>json boolean files[].is_restart_required: Whether the file requires a browser restart to work once installed or not.
    :>json boolean files[].is_webextension: Whether the file is a WebExtension or not.
    :>json int files[].status: The :ref:`status <addon-detail-status>` for a file.
    :>json string files[].url: The (absolute) URL to download a file. Clients using this API can append an optional ``src`` query parameter to the url which would indicate the source of the request (See :ref:`download sources <download-sources>`).
    :>json array files[].permissions[]: Array of the webextension permissions for this File, as strings.  Empty for non-webextensions.
    :>json object license: Object holding information about the license for the version. For performance reasons this field is omitted from add-on search endpoint.
    :>json string|object|null license.name: The name of the license (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null license.text: The text of the license (See :ref:`translated fields <api-overview-translations>`). For performance reasons this field is omitted from add-on detail endpoint.
    :>json string|null license.url: The URL of the full text of license.
    :>json string|object|null release_notes: The release notes for this version (See :ref:`translated fields <api-overview-translations>`). For performance reasons this field is omitted from add-on search endpoint.
    :>json string reviewed: The date the version was reviewed at.
    :>json boolean is_strict_compatibility_enabled: Whether or not this version has `strictCompatibility <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#strictCompatibility>`_. set.
    :>json string version: The version number string for the version.


----------------------------
Add-on Feature Compatibility
----------------------------

.. _addon-feature-compatibility:

This endpoint allows you to fetch feature compatibility information for a
a specific add-on by id, slug or guid.

.. http:get:: /api/v4/addons/addon/(int:id|string:slug|string:guid)/feature_compatibility/

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both:

            * authentication
            * reviewer permissions or an account listed as a developer of the add-on

    :>json int e10s: The add-on e10s compatibility. Can be one of the following:

    =======================  ==========================================================
                      Value  Description
    =======================  ==========================================================
                 compatible  multiprocessCompatible marked as true in the install.rdf.
    compatible-webextension  A WebExtension, so compatible.
               incompatible  multiprocessCompatible marked as false in the install.rdf.
                    unknown  multiprocessCompatible has not been set.
    =======================  ==========================================================

------------------------------
Add-on EULA and Privacy Policy
------------------------------

.. _addon-eula-policy:

This endpoint allows you to fetch an add-on EULA and privacy policy.

.. http:get:: /api/v4/addons/addon/(int:id|string:slug|string:guid)/eula_policy/

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both:

            * authentication
            * reviewer permissions or an account listed as a developer of the add-on

    :>json string|object|null eula: The text of the EULA, if present (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null privacy_policy: The text of the Privacy Policy, if present (See :ref:`translated fields <api-overview-translations>`).


--------------
Language Tools
--------------

.. _addon-language-tools:

This endpoint allows you to list all public language tools add-ons available
on AMO.

.. http:get:: /api/v4/addons/language-tools/

    .. note::
        Because this endpoint is intended to be used to feed a page that
        displays all available language tools in a single page, it is not
        paginated as normal, and instead will return all results without
        obeying regular pagination parameters. The ordering is left undefined,
        it's up to the clients to re-order results as needed before displaying
        the add-ons to the end-users.

        In addition, the results can be cached for up to 24 hours, based on the
        full URL used in the request.

    :query string app: Mandatory. Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when both the ``app`` and ``type`` parameters are also present, and only makes sense for Language Packs, since Dictionaries are always compatible with every application version.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string type: Mandatory when ``appversion`` is present. Filter by :ref:`add-on type <addon-detail-type>`. The default is to return both Language Packs or Dictionaries.
    :>json array results: An array of language tools.
    :>json int results[].id: The add-on id on AMO.
    :>json object results[].current_compatible_version: Object holding the latest publicly available :ref:`version <version-detail-object>` of the add-on compatible with the ``appversion`` parameter used. Only present when ``appversion`` is passed and valid. For performance reasons, only the following version properties are returned on the object: ``id``, ``files``, ``reviewed``, and ``version``.
    :>json string results[].default_locale: The add-on default locale for translations.
    :>json string|object|null results[].name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :>json string results[].guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json string results[].locale_disambiguation: Free text field allowing clients to distinguish between multiple dictionaries in the same locale but different spellings. Only present when using the Language Tools endpoint.
    :>json string results[].slug: The add-on slug.
    :>json string results[].target_locale: For dictionaries and language packs, the locale the add-on is meant for. Only present when using the Language Tools endpoint.
    :>json string results[].type: The :ref:`add-on type <addon-detail-type>`.
    :>json string results[].url: The (absolute) add-on detail URL.

.. _`valid application versions`: https://addons.mozilla.org/en-US/firefox/pages/appversions/


-------------------
Replacement Add-ons
-------------------

.. _addon-replacement-addons:

This endpoint returns a list of suggested replacements for legacy add-ons that are unsupported in Firefox 57.  Added to support the TAAR recommendation service.

.. http:get:: /api/v4/addons/replacement-addon/

    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The total number of replacements.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of replacements matches.
    :>json string results[].guid: The extension identifier of the legacy add-on.
    :>json string results[].replacement[]: An array of guids for the replacements add-ons.  If there is a direct replacement this will be a list of one add-on guid.  The list can be empty if all the replacement add-ons are invalid (e.g. not publicly available on AMO).  The list will also be empty if the replacement is to a url that is not an addon or collection.


---------------
Compat Override
---------------

.. _addon-compat-override:

This endpoint allows compatibility overrides specified by AMO admins to be searched.
Compatibilty overrides are used within Firefox i(and other toolkit applications e.g. Thunderbird) to change compatibility of installed add-ons where they have stopped working correctly in new release of Firefox, etc.

.. http:get:: /api/v4/addons/compat-override/

    :query string guid: Filter by exact add-on guid. Multiple guids can be specified, separated by comma(s), in which case any add-ons matching any of the guids will be returned.  As guids are unique there should be at most one add-on result per guid specified.
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of compat overrides.
    :>json int|null results[].addon_id: The add-on identifier on AMO, if specified.
    :>json string results[].addon_guid: The add-on extension identifier.
    :>json string results[].name: A description entered by AMO admins to describe the override.
    :>json array results[].version_ranges: An array of affected versions of the add-on.
    :>json string results[].version_ranges[].addon_min_version: minimum version of the add-on to be disabled.
    :>json string results[].version_ranges[].addon_max_version: maximum version of the add-on to be disabled.
    :>json array results[].version_ranges[].applications: An array of affected applications for this range of versions.
    :>json string results[].version_ranges[].applications[].name: Application name (e.g. Firefox).
    :>json int results[].version_ranges[].applications[].id: Application id on AMO.
    :>json string results[].version_ranges[].applications[].min_version: minimum version of the application to be disabled in.
    :>json string results[].version_ranges[].applications[].max_version: maximum version of the application to be disabled in.
    :>json string results[].version_ranges[].applications[].guid: Application `guid <https://addons.mozilla.org/en-US/firefox/pages/appversions/>`_.


---------------
Recommendations
---------------

.. _addon-recommendations:

This endpoint provides recommendations of other addons to install, fetched from the `recommendation service <https://github.com/mozilla/taar>`_.
Four recommendations are fetched, but only valid, publicly available addons are shown (so max 4 will be returned, and possibly less).

.. http:get:: /api/v4/addons/recommendations/

    :query string guid: Fetch recommendations for this add-on guid.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query boolean recommended: Fetch recommendations from the recommendation service, or return a curated fallback list instead.
    :>json string outcome: Outcome of the response returned.  Will be either: ``recommended`` - responses from recommendation service; ``recommended_fallback`` - service timed out or returned empty results so we returned fallback; ``curated`` - ``recommended=False`` was requested so fallback returned.
    :>json string|null fallback_reason: if ``outcome`` was ``recommended_fallback`` then the reason why.  Will be either: ``timeout`` or ``no_results``.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`. The following fields are omitted for performance reasons: ``release_notes`` and ``license`` fields on ``current_version`` and ``current_beta_version``, as well as ``picture_url`` from ``authors``.
