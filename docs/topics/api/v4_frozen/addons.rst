=======
Add-ons
=======

.. note::

    These v4 APIs are now frozen.
    See :ref:`the API versions available<api-versions-list>` for details of the
    different API versions available.
    The only authentication method available at
    the moment is :ref:`the internal one<v4-api-auth-internal>`.


------
Search
------

.. _v4-addon-search:

This endpoint allows you to search through public add-ons.

.. http:get:: /api/v4/addons/search/

    :query string q: The search query. The maximum length allowed is 100 characters.
    :query string app: Filter by :ref:`add-on application <v4-addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string author: Filter by exact (listed) author username or user id. Multiple author usernames or ids can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string category: Filter by :ref:`category slug <v4-category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string color: (Experimental) Filter by color in RGB hex format, trying to find themes that approximately match the specified color. Only works for static themes.
    :query string exclude_addons: Exclude add-ons by ``slug`` or ``id``. Multiple add-ons can be specified, separated by comma(s).
    :query string guid: Filter by exact add-on guid. Multiple guids can be specified, separated by comma(s), in which case any add-ons matching any of the guids will be returned.  As guids are unique there should be at most one add-on result per guid specified. For usage with Firefox, instead of separating multiple guids by comma(s), a single guid can be passed in base64url format, prefixed by the ``rta:`` string.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :query string promoted: Filter to add-ons in a specific :ref:`promoted category <v4-addon-detail-promoted-category>`.  Can be combined with `app`.   Multiple promoted categories can be specified, separated by comma(s), in which case any add-ons in any of the promotions will be returned.
    :query string tag: Filter by exact tag name. Multiple tag names can be specified, separated by comma(s), in which case add-ons containing *all* specified tags are returned.
    :query string type: Filter by :ref:`add-on type <v4-addon-detail-type>`.  Multiple types can be specified, separated by comma(s), in which case add-ons that are any of the matching types are returned.
    :query string sort: The sort parameter. The available parameters are documented in the :ref:`table below <v4-addon-search-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <v4-addon-detail-object>`. As described below, the following fields are omitted for performance reasons: ``release_notes`` and ``license`` fields on ``current_version`` as well as ``picture_url`` from ``authors``. The special ``_score`` property is added to each add-on object, it contains a float value representing the relevancy of each add-on for the given query.

.. _v4-addon-search-sort:

    Available sorting parameters:

    ==============  ==========================================================
         Parameter  Description
    ==============  ==========================================================
           created  Creation date, descending.
         downloads  Number of weekly downloads, descending.
           hotness  Hotness (average number of users progression), descending.
            random  Random ordering. Only available when no search query is
                    passed and when filtering to only return promoted add-ons.
            rating  Bayesian rating, descending.
       recommended  Promoted addons in the recommended category above
                    non-recommended add-ons. Only available combined with
                    another sort - ignored on its own.
                    Also ignored if combined with relevance as it already takes
                    into account recommended status.
         relevance  Search query relevance, descending.  Ignored without a
                    query.
           updated  Last updated date, descending.
             users  Average number of daily users, descending.
    ==============  ==========================================================

    The default behavior is to sort by relevance if a search query (``q``)
    is present; otherwise place recommended add-ons first, then non recommended
    add-ons, then sorted by average daily users, descending. (``sort=recommended,users``).
    This is the default on AMO dev server.

    You can combine multiple parameters by separating them with a comma.
    For instance, to sort search results by downloads and then by creation
    date, use ``sort=downloads,created``. The only exception is the ``random``
    sort parameter, which is only available alone.


------------
Autocomplete
------------

.. _v4-addon-autocomplete:

Similar to :ref:`add-ons search endpoint <v4-addon-search>` above, this endpoint
allows you to search through public add-ons. Because it's meant as a backend
for autocomplete though, there are a couple key differences:

  - No pagination is supported. There are no ``next``, ``prev`` or ``count``
    fields, and passing ``page_size`` or ``page`` has no effect, a maximum of 10
    results will be returned at all times.
  - Only a subset of fields are returned.
  - ``sort`` is not supported. Sort order is always ``relevance`` if ``q`` is
    provided, or the :ref:`search default <v4-addon-search-sort>` otherwise.

.. http:get:: /api/v4/addons/autocomplete/

    :query string q: The search query.
    :query string app: Filter by :ref:`add-on application <v4-addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string author: Filter by exact (listed) author username. Multiple author names can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string category: Filter by :ref:`category slug <v4-category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :query string tag: Filter by exact tag name. Multiple tag names can be specified, separated by comma(s).
    :query string type: Filter by :ref:`add-on type <v4-addon-detail-type>`.
    :>json array results: An array of :ref:`add-ons <v4-addon-detail-object>`. Only the ``id``, ``icon_url``, ``name``, ``promoted``, ``type`` and ``url`` fields are supported though.


------
Detail
------

.. _v4-addon-detail:

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

    .. _v4-addon-detail-object:

    :query string app: Used in conjunction with ``appversion`` below to alter ``current_version`` behaviour. Need to be a valid :ref:`add-on application <v4-addon-detail-application>`.
    :query string appversion: Make ``current_version`` return the latest public version of the add-on compatible with the given application version, if possible, otherwise fall back on the generic implementation. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present. Currently only compatible with language packs through the add-on detail API, ignored for other types of add-ons and APIs.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`Translated Fields <v4-api-overview-translations>`)
    :query string wrap_outgoing_links: (v3/v4 only) If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <v4-api-overview-outgoing>`)
    :>json int id: The add-on id on AMO.
    :>json array authors: Array holding information about the authors for the add-on.
    :>json int authors[].id: The id for an author.
    :>json string authors[].name: The name for an author.
    :>json string authors[].url: The link to the profile page for an author.
    :>json string authors[].username: The username for an author.
    :>json string authors[].picture_url: URL to a photo of the user, or `/static/img/anon_user.png` if not set. For performance reasons this field is omitted from the search endpoint.
    :>json int average_daily_users: The average number of users for the add-on (updated daily).
    :>json object categories: Object holding the categories the add-on belongs to.
    :>json array categories[app_name]: Array holding the :ref:`category slugs <v4-category-list>` the add-on belongs to for a given :ref:`add-on application <v4-addon-detail-application>`. (Combine with the add-on ``type`` to determine the name of the category).
    :>json string|object|null contributions_url: URL to the (external) webpage where the addon's authors collect monetary contributions, if set. Can be an empty value.  (See :ref:`Outgoing Links <v4-api-overview-outgoing>`)
    :>json string created: The date the add-on was created.
    :>json object current_version: Object holding the current :ref:`version <v4-version-detail-object>` of the add-on. For performance reasons the ``license`` field omits the ``text`` property from both the search and detail endpoints.
    :>json string default_locale: The add-on default locale for translations.
    :>json string|object|null description: The add-on description (See :ref:`translated fields <v4-api-overview-translations>`). This field might contain some HTML tags.
    :>json string|object|null developer_comments: Additional information about the add-on provided by the developer. (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string edit_url: The URL to the developer edit page for the add-on.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json boolean has_eula: The add-on has an End-User License Agreement that the user needs to agree with before installing (See :ref:`add-on EULA and privacy policy <v4-addon-eula-policy>`).
    :>json boolean has_privacy_policy: The add-on has a Privacy Policy (See :ref:`add-on EULA and privacy policy <v4-addon-eula-policy>`).
    :>json string|object|null homepage: The add-on homepage (See :ref:`translated fields <v4-api-overview-translations>` and :ref:`Outgoing Links <v4-api-overview-outgoing>`).
    :>json string icon_url: The URL to icon for the add-on (including a cachebusting query string).
    :>json object icons: An object holding the URLs to an add-ons icon including a cachebusting query string as values and their size as properties. Currently exposes 32, 64, 128 pixels wide icons.
    :>json boolean is_disabled: Whether the add-on is disabled or not.
    :>json boolean is_experimental: Whether the add-on has been marked by the developer as experimental or not.
    :>json string|object|null name: The add-on name (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json object|null latest_unlisted_version: Object holding the latest unlisted :ref:`version <v4-version-detail-object>` of the add-on. This field is only present if the user has unlisted reviewer permissions, or is listed as a developer of the add-on.
    :>json array previews: Array holding information about the previews for the add-on.
    :>json int previews[].id: The id for a preview.
    :>json string|object|null previews[].caption: The caption describing a preview (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json int previews[].image_size[]: width, height dimensions of of the preview image.
    :>json string previews[].image_url: The URL (including a cachebusting query string) to the preview image.
    :>json int previews[].thumbnail_size[]: width, height dimensions of of the preview image thumbnail.
    :>json string previews[].thumbnail_url: The URL (including a cachebusting query string) to the preview image thumbnail.
    :>json object|null promoted: Object holding promotion information about the add-on. Null if the add-on is not currently promoted.
    :>json string promoted.category: The name of the :ref:`promoted category <v4-addon-detail-promoted-category>` for the add-on.
    :>json array promoted.apps[]: Array of the :ref:`applications <v4-addon-detail-application>` for which the add-on is promoted.
    :>json object ratings: Object holding ratings summary information about the add-on.
    :>json int ratings.count: The total number of user ratings for the add-on.
    :>json int ratings.text_count: The number of user ratings with review text for the add-on.
    :>json string ratings_url: The URL to the user ratings list page for the add-on.
    :>json float ratings.average: The average user rating for the add-on.
    :>json float ratings.bayesian_average: The bayesian average user rating for the add-on.
    :>json boolean requires_payment: Does the add-on require payment, non-free services or software, or additional hardware.
    :>json string review_url: The URL to the reviewer review page for the add-on.
    :>json string slug: The add-on slug.
    :>json string status: The :ref:`add-on status <v4-addon-detail-status>`.
    :>json string|object|null summary: The add-on summary (See :ref:`translated fields <v4-api-overview-translations>`). This field supports "linkification" and therefore might contain HTML hyperlinks.
    :>json string|object|null support_email: The add-on support email (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string|object|null support_url: The add-on support URL (See :ref:`translated fields <v4-api-overview-translations>` and :ref:`Outgoing Links <v4-api-overview-outgoing>`).
    :>json array tags: List containing the text of the tags set on the add-on.
    :>json string type: The :ref:`add-on type <v4-addon-detail-type>`.
    :>json string url: The (absolute) add-on detail URL.
    :>json string versions_url: The URL to the version history page for the add-on.
    :>json int weekly_downloads: The number of downloads for the add-on in the last week. Not present for lightweight themes.


.. _v4-addon-detail-status:

    Possible values for the ``status`` field / parameter:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
            public  Fully Reviewed
           deleted  Deleted
          disabled  Disabled by Mozilla
         nominated  Awaiting Full Review
        incomplete  Incomplete
        unreviewed  Awaiting Preliminary Review
    ==============  ==========================================================


.. _v4-addon-detail-application:

    Possible values for the keys in the ``compatibility`` field, as well as the
    ``app`` parameter in the search API:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
           android  Firefox for Android
           firefox  Firefox
    ==============  ==========================================================

    .. note::
        See the :ref:`supported versions <applications-version-list>`.

.. _v4-addon-detail-platform:

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

.. _v4-addon-detail-type:

    Possible values for the ``type`` field / parameter:

    .. note::

        For backwards-compatibility reasons, the value for type of ``theme``
        refers to a deprecated XUL Complete Theme.  ``persona`` are another
        type of depreated theme.
        New webextension packaged non-dynamic themes are ``statictheme``.

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
             theme  Depreated.  Theme (Complete Theme, XUL-based)
            search  Search Engine
           persona  Deprecated.  Theme (Lightweight Theme, persona)
          language  Language Pack (Application)
         extension  Extension
        dictionary  Dictionary
       statictheme  Theme (Static Theme)
    ==============  ==========================================================

.. _v4-addon-detail-promoted-category:

    Possible values for the ``promoted.category`` field:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
              line  "By Firefox" category
       recommended  Recommended category
         spotlight  Spotlight category
         strategic  Strategic category
            badged  A meta category that's available for the ``promoted``
                    search filter that is all the categories we expect an API
                    client to expose as "reviewed" by Mozilla.
                    Currently equal to ``line&recommended``.
    ==============  ==========================================================

-----------------------------
Add-on and Version Submission
-----------------------------

See :ref:`Uploading a version <v4-upload-version>`.

-------------
Versions List
-------------

.. _v4-version-list:

This endpoint allows you to list all versions belonging to a specific add-on.

.. http:get:: /api/v4/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both:

            * authentication
            * reviewer permissions or an account listed as a developer of the add-on

    :query string filter: The :ref:`filter <v4-version-filtering-param>` to apply.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The number of versions for this add-on.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`versions <v4-version-detail-object>`.

.. _v4-version-filtering-param:

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

.. _v4-version-detail:

This endpoint allows you to fetch a single version belonging to a specific add-on.

.. http:get:: /api/v4/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id)/

    .. _v4-version-detail-object:

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :>json int id: The version id.
    :>json string channel: The version channel, which determines its visibility on the site. Can be either ``unlisted`` or ``listed``.
    :>json object compatibility:
        Object detailing which :ref:`applications <v4-addon-detail-application>` the version is compatible with.
        The exact min/max version numbers in the object correspond to the :ref:`supported versions<applications-version-list>`.
        Example:

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
    :>json boolean files[].is_mozilla_signed_extension: Whether the file was signed with a Mozilla internal certificate or not.
    :>json boolean files[].is_restart_required: Whether the file requires a browser restart to work once installed or not.
    :>json boolean files[].is_webextension: Whether the file is a WebExtension or not.
    :>json array files[].optional_permissions[]: Array of the optional webextension permissions for this File, as strings. Empty for non-webextensions.
    :>json array files[].permissions[]: Array of the webextension permissions for this File, as strings. Empty for non-webextensions.
    :>json string files[].platform: The :ref:`platform <v4-addon-detail-platform>` for a file.
    :>json int files[].size: The size for a file, in bytes.
    :>json int files[].status: The :ref:`status <v4-addon-detail-status>` for a file.
    :>json string files[].url: The (absolute) URL to download a file.
    :>json object license: Object holding information about the license for the version.
    :>json boolean license.is_custom: Whether the license text has been provided by the developer, or not.  (When ``false`` the license is one of the common, predefined, licenses).
    :>json string|object|null license.name: The name of the license (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string|object|null license.text: The text of the license (See :ref:`translated fields <v4-api-overview-translations>`). For performance reasons this field is omitted from add-on detail endpoint.
    :>json string|null license.url: The URL of the full text of license.
    :>json string|object|null release_notes: The release notes for this version (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string reviewed: The date the version was reviewed at.
    :>json boolean is_strict_compatibility_enabled: Whether or not this version has `strictCompatibility <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#strictCompatibility>`_. set.
    :>json string version: The version number string for the version.


------------------------------
Add-on EULA and Privacy Policy
------------------------------

.. _v4-addon-eula-policy:

This endpoint allows you to fetch an add-on EULA and privacy policy.

.. http:get:: /api/v4/addons/addon/(int:id|string:slug|string:guid)/eula_policy/

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both:

            * authentication
            * reviewer permissions or an account listed as a developer of the add-on

    :>json string|object|null eula: The text of the EULA, if present (See :ref:`v4-translated fields <api-overview-translations>`).
    :>json string|object|null privacy_policy: The text of the Privacy Policy, if present (See :ref:`v4-translated fields <api-overview-translations>`).


--------------
Language Tools
--------------

.. _v4-addon-language-tools:

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

    :query string app: Mandatory. Filter by :ref:`add-on application <v4-addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when both the ``app`` and ``type`` parameters are also present, and only makes sense for Language Packs, since Dictionaries are always compatible with every application version.
    :query string author: Filter by exact (listed) author username. Multiple author names can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :query string type: Mandatory when ``appversion`` is present. Filter by :ref:`add-on type <v4-addon-detail-type>`. The default is to return both Language Packs or Dictionaries.
    :>json array results: An array of language tools.
    :>json int results[].id: The add-on id on AMO.
    :>json object results[].current_compatible_version: Object holding the latest publicly available :ref:`version <v4-version-detail-object>` of the add-on compatible with the ``appversion`` parameter used. Only present when ``appversion`` is passed and valid. For performance reasons, only the following version properties are returned on the object: ``id``, ``files``, ``reviewed``, and ``version``.
    :>json string results[].default_locale: The add-on default locale for translations.
    :>json string|object|null results[].name: The add-on name (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string results[].guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json string results[].slug: The add-on slug.
    :>json string results[].target_locale: For dictionaries and language packs, the locale the add-on is meant for. Only present when using the Language Tools endpoint.
    :>json string results[].type: The :ref:`add-on type <v4-addon-detail-type>`.
    :>json string results[].url: The (absolute) add-on detail URL.


-------------------
Replacement Add-ons
-------------------

.. _v4-addon-replacement-addons:

This endpoint returns a list of suggested replacements for legacy add-ons that are unsupported in Firefox 57.

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
Recommendations
---------------

.. _v4-addon-recommendations:

This endpoint provides recommendations of other addons to install. Maximum four recommendations will be returned.

.. http:get:: /api/v4/addons/recommendations/

    :query string guid: Fetch recommendations for this add-on guid.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :query boolean recommended: Ignored.
    :>json string outcome: Outcome of the response returned. Will always be ``curated``.
    :>json null fallback_reason: Always null.:>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <v4-addon-detail-object>`. The following fields are omitted for performance reasons: ``release_notes`` and ``license`` fields on ``current_version`` and ``current_beta_version``, as well as ``picture_url`` from ``authors``.
