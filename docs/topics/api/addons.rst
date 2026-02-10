=======
Add-ons
=======

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.


------
Search
------

.. _addon-search:

This endpoint allows you to search through public add-ons.

.. http:get:: /api/v5/addons/search/

    :query string q: The search query. The maximum length allowed is 100 characters.
    :query string app: Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string author: Filter by exact (listed) author username or user id. Multiple author usernames or ids can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string category: Filter by :ref:`category slug <category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string color: (Experimental) Filter by color in RGB hex format, trying to find themes that approximately match the specified color. Only works for static themes.
    :query string created: Filter to add-on that have a creation date matching a :ref:`threshold value <addon-threshold-param>`. ``YYYY-MM-DD``, ``YYYY-MM-DDTHH:MM``, ``YYYY-MM-DDTHH:MM:SS`` or milliseconds timestamps are supported.
    :query string exclude_addons: Exclude add-ons by ``slug`` or ``id``. Multiple add-ons can be specified, separated by comma(s).
    :query string guid: Filter by exact add-on guid. Multiple guids can be specified, separated by comma(s), in which case any add-ons matching any of the guids will be returned.  As guids are unique there should be at most one add-on result per guid specified. For usage with Firefox, instead of separating multiple guids by comma(s), a single guid can be passed in base64url format, prefixed by the ``rta:`` string.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :query string promoted: Filter to add-ons in a specific :ref:`promoted category <addon-detail-promoted-category>`.  Can be combined with `app`.   Multiple promoted categories can be specified, separated by comma(s), in which case any add-ons in any of the promotions will be returned.
    :query string ratings: Filter to add-ons that have average ratings of a :ref:`threshold value <addon-threshold-param>`.
    :query string sort: The sort parameter. The available parameters are documented in the :ref:`table below <addon-search-sort>`.
    :query string tag: Filter by exact tag name. Multiple tag names can be specified, separated by comma(s), in which case add-ons containing *all* specified tags are returned. See :ref:`available tags <tag-list>`
    :query string type: Filter by :ref:`add-on type <addon-detail-type>`.  Multiple types can be specified, separated by comma(s), in which case add-ons that are any of the matching types are returned.
    :query string updated: Filter to add-on that have a last updated date matching a :ref:`threshold value <addon-threshold-param>`. ``YYYY-MM-DD``, ``YYYY-MM-DDTHH:MM``, ``YYYY-MM-DDTHH:MM:SS`` or milliseconds timestamps are supported.
    :query string users: Filter to add-ons that have average daily users of a :ref:`threshold value <addon-threshold-param>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`. As described below, the following fields are omitted for performance reasons: ``release_notes`` and ``license`` fields on ``current_version`` as well as ``picture_url`` from ``authors``. The special ``_score`` property is added to each add-on object, it contains a float value representing the relevancy of each add-on for the given query.

.. _addon-search-sort:

    Available sorting parameters:

    ==============  ==========================================================
         Parameter  Description
    ==============  ==========================================================
           created  Creation date, descending.
         downloads  Number of weekly downloads, descending.
           hotness  Hotness (average number of users progression), descending.
            random  Random ordering. Only available when no search query is
                    passed and when filtering to only return promoted add-ons.
           ratings  Bayesian rating, descending.
            rating  Bayesian rating, descending (deprecated, backwards-compatibility only).
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


.. _addon-threshold-param:

    Threshold style parameters allow queries against numeric or date-time values using comparison.

    The following is supported (examples for query parameter `foo`):
        * greater than ``foo__gt`` (example query: ?foo__gt=10.1)
        * less than ``foo__lt`` (example query: ?foo__lt=10.1)
        * greater than or equal to ``foo__gte`` (example query: ?foo__gte=10.1)
        * less than or equal to ``foo__lte`` (example query: ?foo__lte=10.1)
        * equal to ``foo`` (example query: ?foo=10.1)


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
  - ``sort`` is not supported. Sort order is always ``relevance`` if ``q`` is
    provided, or the :ref:`search default <addon-search-sort>` otherwise.

.. http:get:: /api/v5/addons/autocomplete/

    :query string q: The search query.
    :query string app: Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :query string author: Filter by exact (listed) author username. Multiple author names can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string category: Filter by :ref:`category slug <category-list>`. ``app`` and ``type`` parameters need to be set, otherwise this parameter is ignored.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string tag: Filter by exact tag name. Multiple tag names can be specified, separated by comma(s), in which case add-ons containing *all* specified tags are returned. See :ref:`available tags <tag-list>`
    :query string type: Filter by :ref:`add-on type <addon-detail-type>`.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`. Only the ``id``, ``icon_url``, ``icons``, ``name``, ``promoted``, ``type`` and ``url`` fields are supported though.


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

.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/

    .. _addon-detail-object:

    :query string app: Used in conjunction with ``appversion`` below to alter ``current_version`` behaviour. Need to be a valid :ref:`add-on application <addon-detail-application>`.
    :query string appversion: Make ``current_version`` return the latest public version of the add-on compatible with the given application version, if possible, otherwise fall back on the generic implementation. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present. Currently only compatible with language packs through the add-on detail API, ignored for other types of add-ons and APIs.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`Translated Fields <api-overview-translations>`)
    :query boolean show_grouped_ratings: Whether or not to show ratings aggregates in the ``ratings`` object (Use "true"/"1" as truthy values, "0"/"false" as falsy ones).
    :>json int id: The add-on id on AMO.
    :>json array authors: Array holding information about the authors for the add-on.
    :>json int authors[].id: The user id for an author.
    :>json string authors[].name: The name for an author.
    :>json string authors[].url: The link to the profile page for an author.
    :>json string authors[].username: The username for an author.
    :>json string authors[].picture_url: URL to a photo of the user, or `/static/img/anon_user.png` if not set. For performance reasons this field is omitted from the search endpoint.
    :>json int average_daily_users: The average number of users for the add-on (updated daily).
    :>json object categories: Object holding the categories the add-on belongs to.
    :>json array categories[app_name]: Array holding the :ref:`category slugs <category-list>` the add-on belongs to for a given :ref:`add-on application <addon-detail-application>`. (Combine with the add-on ``type`` to determine the name of the category).
    :>json object|null contributions_url: URL to the (external) webpage where the addon's authors collect monetary contributions, if set. Can be an empty value.  (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json string created: The date the add-on was created.
    :>json object current_version: Object holding the current :ref:`version <version-detail-object>` of the add-on. For performance reasons the ``license`` field omits the ``text`` property from both the search and detail endpoints.
    :>json string default_locale: The add-on default locale for translations.
    :>json object|null description: The add-on description (See :ref:`translated fields <api-overview-translations>`). This field might contain markdown.
    :>json object|null developer_comments: Additional information about the add-on provided by the developer. (See :ref:`translated fields <api-overview-translations>`).
    :>json string edit_url: The URL to the developer edit page for the add-on.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json boolean has_eula: The add-on has an End-User License Agreement that the user needs to agree with before installing (See :ref:`add-on EULA and privacy policy <addon-eula-policy>`).
    :>json boolean has_privacy_policy: The add-on has a Privacy Policy (See :ref:`add-on EULA and privacy policy <addon-eula-policy>`).
    :>json object|null homepage: The add-on homepage (See :ref:`translated fields <api-overview-translations>` and :ref:`Outgoing Links <api-overview-outgoing>`).
    :>json string icon_url: The URL to icon for the add-on (including a cachebusting query string).
    :>json object icons: An object holding the URLs to an add-ons icon including a cachebusting query string as values and their size as properties. Currently exposes 32, 64, 128 pixels wide icons.
    :>json boolean is_disabled: Whether the add-on is disabled or not.
    :>json boolean is_experimental: Whether the add-on has been marked by the developer as experimental or not.
    :>json boolean|null is_noindexed: Whether the add-on should be indexed or not indexed for SEO. Note that the search endpoint will always return a ``null`` value.
    :>json object|null name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json object|null latest_unlisted_version: Object holding the latest unlisted :ref:`version <version-detail-object>` of the add-on. This field is only present if the user has unlisted reviewer permissions, or is listed as a developer of the add-on.
    :>json array previews: Array holding information about the previews for the add-on.
    :>json int previews[].id: The id for a preview.
    :>json object|null previews[].caption: The caption describing a preview (See :ref:`translated fields <api-overview-translations>`).
    :>json int previews[].image_size[]: width, height dimensions of of the preview image.
    :>json string previews[].image_url: The URL (including a cachebusting query string) to the preview image.
    :>json int position: The position in the list of previews images.
    :>json int previews[].thumbnail_size[]: width, height dimensions of of the preview image thumbnail.
    :>json string previews[].thumbnail_url: The URL (including a cachebusting query string) to the preview image thumbnail.
    :>json array promoted: Array holding promotion information about the add-on.
    :>json string promoted[].category: The name of the :ref:`promoted category <addon-detail-promoted-category>` for the add-on.
    :>json array promoted[].apps[]: Array of the :ref:`applications <addon-detail-application>` for which the add-on is promoted.
    :>json object ratings: Object holding ratings summary information about the add-on.
    :>json int ratings.count: The total number of user ratings for the add-on.
    :>json int ratings.text_count: The number of user ratings with review text for the add-on.
    :>json string ratings_url: The URL to the user ratings list page for the add-on.
    :>json float ratings.average: The average user rating for the add-on.
    :>json float ratings.bayesian_average: The bayesian average user rating for the add-on.
    :>json object ratings.grouped_counts: Object with aggregate counts for ratings.  Only included when ``show_grouped_ratings`` is present in the request.
    :>json int ratings.grouped_counts.1: the count of ratings with a score of 1.
    :>json int ratings.grouped_counts.2: the count of ratings with a score of 2.
    :>json int ratings.grouped_counts.3: the count of ratings with a score of 3.
    :>json int ratings.grouped_counts.4: the count of ratings with a score of 4.
    :>json int ratings.grouped_counts.5: the count of ratings with a score of 5.
    :>json boolean requires_payment: Does the add-on require payment, non-free services or software, or additional hardware.
    :>json string review_url: The URL to the reviewer review page for the add-on.
    :>json string slug: The add-on slug.
    :>json string status: The :ref:`add-on status <addon-detail-status>`.
    :>json object|null summary: The add-on summary (See :ref:`translated fields <api-overview-translations>`).
    :>json object|null support_email: The add-on support email (See :ref:`translated fields <api-overview-translations>`).
    :>json object|null support_url: The add-on support URL (See :ref:`translated fields <api-overview-translations>` and :ref:`Outgoing Links <api-overview-outgoing>`).
    :>json array tags: List containing the tag names set on the add-on.
    :>json string type: The :ref:`add-on type <addon-detail-type>`.
    :>json string url: The (absolute) add-on detail URL.
    :>json object version: For create or update requests that included a :ref:`version <version-create-request>` only. Object holding the :ref:`version <version-detail-object>` that was submitted.
    :>json string versions_url: The URL to the version history page for the add-on.
    :>json int weekly_downloads: The number of downloads for the add-on in the last week. Not present for lightweight themes.


.. _addon-detail-status:

    Possible values for the add-on ``status`` field / parameter:

    ==============  ==============================================================
             Value  Description
    ==============  ==============================================================
            public  Approved
           deleted  Deleted
          disabled  Disabled by Mozilla
          rejected  Listing content :ref:`rejected <listing-content-review>`
         nominated  Awaiting Review
        incomplete  Incomplete - no approved listed versions
    ==============  ==============================================================


.. _addon-detail-application:

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


.. _addon-detail-type:

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

.. _addon-detail-promoted-category:

    Possible values for the ``promoted.category`` field:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
              line  "By Firefox" category
           notable  Notable category
       recommended  Recommended category
         spotlight  Spotlight category
         strategic  Strategic category
            badged  A meta category that's available for the ``promoted``
                    search filter that is all the categories we expect an API
                    client to expose as "reviewed" by Mozilla.
                    Currently equal to ``line&recommended``.
    ==============  ==========================================================


------
Create
------

.. _addon-create:

This endpoint allows a submission of an upload to create a new add-on and setting other AMO metadata.

To create an add-on with a listed version from an upload (an :ref:`upload <upload-create>`
that has channel == ``listed``) certain metadata must be defined - a version ``license``, an
add-on ``name``, an add-on ``summary``, and add-on categories for each app the version
is compatible with.

    .. note::
        This API requires :doc:`authentication <auth>`.

.. http:post:: /api/v5/addons/addon/

    .. _addon-create-request:

    :<json object categories: Object holding the categories the add-on belongs to.
    :<json array categories[app_name]: Array holding the :ref:`category slugs <category-list>` the add-on belongs to for a given :ref:`add-on application <addon-detail-application>`.
    :<json string contributions_url: URL to the (external) webpage where the addon's authors collect monetary contributions.  Only a limited number of services are `supported <https://github.com/mozilla/addons-server/blob/0b5db7d544a21f6b887e8e8032496778234ade33/src/olympia/constants/base.py#L214:L226>`_.
    :<json string default_locale: The fallback locale for translated fields for this add-on. Note this only applies to the fields here - the default locale for :ref:`version release notes <version-create-request>` and custom license text is fixed to `en-US`.
    :<json object|null description: The add-on description (See :ref:`translated fields <api-overview-translations>`). This field can contain some Markdown.
    :<json object|null developer_comments: Additional information about the add-on. (See :ref:`translated fields <api-overview-translations>`).
    :<json object|null homepage: The add-on homepage (See :ref:`translated fields <api-overview-translations>` and :ref:`Outgoing Links <api-overview-outgoing>`).
    :<json boolean is_disabled: Whether the add-on is disabled or not.
    :<json boolean is_experimental: Whether the add-on should be marked as experimental or not.
    :<json object|null name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :<json boolean requires_payment: Does the add-on require payment, non-free services or software, or additional hardware.
    :<json string slug: The add-on slug.  Valid slugs must only contain letters, numbers (`categories L and N <http://www.unicode.org/reports/tr44/tr44-4.html#GC_Values_Table>`_), ``-``, ``_``, ``~``, and can't be all numeric.
    :<json object|null summary: The add-on summary (See :ref:`translated fields <api-overview-translations>`).
    :<json object|null support_email: The add-on support email (See :ref:`translated fields <api-overview-translations>`).
    :<json array tags: List containing the tag names to set on the add-on - see :ref:`available tags <tag-list>`.
    :<json object version: Object containing the :ref:`version <version-create-request>` to create this addon with.

    **Response:**
    See :ref:`add-on <addon-detail-object>`


----
Edit
----

.. _addon-edit:

This endpoint allows an add-on's AMO metadata to be edited.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

.. http:patch:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/

    .. _addon-edit-request:

    :<json object categories: Object holding the categories the add-on belongs to.
    :<json array categories[app_name]: Array holding the :ref:`category slugs <category-list>` the add-on belongs to for a given :ref:`add-on application <addon-detail-application>`.
    :<json string contributions_url: URL to the (external) webpage where the addon's authors collect monetary contributions.  Only a limited number of services are `supported <https://github.com/mozilla/addons-server/blob/0b5db7d544a21f6b887e8e8032496778234ade33/src/olympia/constants/base.py#L214:L226>`_.
    :<json string default_locale: The fallback locale for translated fields for this add-on. Note this only applies to the fields here - the default locale for :ref:`version release notes <version-create-request>` and custom license text is fixed to `en-US`.
    :<json object|null description: The add-on description (See :ref:`translated fields <api-overview-translations>`). This field can contain some Markdown.
    :<json object|null developer_comments: Additional information about the add-on. (See :ref:`translated fields <api-overview-translations>`).
    :<json object|null homepage: The add-on homepage (See :ref:`translated fields <api-overview-translations>` and :ref:`Outgoing Links <api-overview-outgoing>`).
    :<json null icon: To clear the icon, i.e. revert to the default add-on icon, send ``null``.  See :ref:`addon icon <addon-icon>` to upload a new icon.
    :<json boolean is_disabled: Whether the add-on is disabled or not.  Note: if the add-on status is :ref:`disabled <addon-detail-status>` the response will always be ``disabled=true`` regardless.
    :<json boolean is_experimental: Whether the add-on should be marked as experimental or not.
    :<json object|null name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :<json boolean requires_payment: Does the add-on require payment, non-free services or software, or additional hardware.
    :<json string slug: The add-on slug.  Valid slugs must only contain letters, numbers (`categories L and N <http://www.unicode.org/reports/tr44/tr44-4.html#GC_Values_Table>`_), ``-``, ``_``, ``~``, and can't be all numeric.
    :<json object|null summary: The add-on summary (See :ref:`translated fields <api-overview-translations>`).
    :<json object|null support_email: The add-on support email (See :ref:`translated fields <api-overview-translations>`).
    :<json array tags: List containing the tag names to set on the add-on - see :ref:`available tags <tag-list>`.


~~~~~~~~~~
Addon Icon
~~~~~~~~~~

.. _addon-icon:

A single add-on icon used on AMO can be uploaded to ``icon``,
where it will be resized as 32, 64, and 128 pixels wide icons as ``icons``.
The resizing is carried out asynchronously  so the urls in the response may not be available immediately.
The image must be square, in either JPEG or PNG format, and we recommend 128x128.

The upload must be sent as multipart form-data rather than JSON.
If desired, some other properties can be set/updated at the same time as ``icon``, but fields that contain complex data structure (list or object) can not, so separate API calls are needed.

Note: as form-data can not include objects, and creating an add-on requires the version to be specified as an object, it's not possible to set ``icons`` during an :ref:`Add-on create <addon-create>`.


.. http:patch:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/

    .. _addon-icon-request-edit:

    :form icon: The icon file being uploaded, or an empty value to clear.
    :reqheader Content-Type: multipart/form-data


--------------------
Put - Create or Edit
--------------------

.. _addon-put:

This endpoint allows a submission of an upload, which will either update an existing add-on and create a new version if the guid already exists, or will create a new add-on if the guid does not exist.
See the :ref:`Add-on Create <addon-create>` documentation for details of the request and restrictions.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on if the add-on exists already.

    .. note::
        The guid in the url must match a guid specified in the manifest.

    .. note::
        A submission that results in a new add-on will have metadata defaults taken from the manifest (e.g. name), but a submission that updates an existing listing will not use data from the manifest.

.. http:put:: /api/v5/addons/addon/(string:guid)/


------
Delete
------

.. _addon-delete:

This endpoint allows an add-on to be deleted.
Because add-on deletion is an irreversible and destructive action an additional token must be retrieved beforehand, and passed as a parameter to the delete endpoint.
Deleting the add-on will permanently delete all versions and files submitted for this add-on, listed or not.
All versions will be soft-blocked (restricted), which will disable and prevent any further installation in Firefox. Existing users can choose to re-enable the add-on.
The add-on ID (``guid``) cannot be restored and will forever be unusable for submission.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on..

.. http:delete:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/

    .. _addon-delete-request:

    :query string delete_confirm: the confirmation token from the :ref:`delete confirm <addon-delete-confirm>` endpoint.


~~~~~~~~~~~~~~
Delete Confirm
~~~~~~~~~~~~~~

.. _addon-delete-confirm:

This endpoint just supplies a special signed token that can be used to confirm deletion of an add-on.
The token is valid for 60 seconds after it's been created, and is only valid for this specific add-on.


    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an owner of the add-on.

.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/delete_confirm/

    .. _addon-delete-confirm-request:

    :>json string delete_confirm: The confirmation token to be used with :ref:`add-on delete <addon-delete>` endpoint.


-------------
Versions List
-------------

.. _version-list:

This endpoint allows you to list all versions belonging to a specific add-on.

.. http:get:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/

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

    .. note::
        This API accepts both version ids and version numbers in the URL. If the version number passed does not contain any dot characters (``.``) it would be considered an ``id``. To avoid this and force a lookup by version number, add a ``v`` prefix to it.

.. http:get:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id|string:version_number)/

    .. _version-detail-object:

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :>json int id: The version id.
    :>json string approval_notes: Information for Mozilla reviewers, for when the add-on is reviewed.  These notes are only visible to Mozilla, and this field is only present if the user has reviewer permissions, or is listed as a developer of the add-on.
    :>json string channel: The version channel, which determines its visibility on the site. Can be either ``unlisted`` or ``listed``.
    :>json object compatibility:
        Object detailing which :ref:`applications <addon-detail-application>` the version is compatible with.
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

    :>json string compatibility[app_name].max: Maximum version of the corresponding app the version is compatible with. Should only be enforced by clients if ``is_strict_compatibility_enabled`` is ``true``.
    :>json string compatibility[app_name].min: Minimum version of the corresponding app the version is compatible with.
    :>json string edit_url: The URL to the developer edit page for the version.
    :>json int file.id: The id for the file.
    :>json string file.created: The creation date for the file.
    :>json string file.hash: The hash for the file.
    :>json boolean file.is_mozilla_signed_extension: Whether the file was signed with a Mozilla internal certificate or not.
    :>json array file.optional_permissions[]: Array of the optional webextension permissions for this File, as strings. Empty for non-webextensions.
    :>json array file.host_permissions[]: Array of the host permissions for this File, as strings. Empty for non-webextensions.
    :>json array file.permissions[]: Array of the webextension permissions for this File, as strings. Empty for non-webextensions.
    :>json array file.data_collection_permissions[]: Array of the data collection permissions for this File, as strings. Empty for non-webextensions.
    :>json array file.optional_data_collection_permissions[]: Array of the optional data collection permissions for this File, as strings. Empty for non-webextensions.
    :>json int file.size: The size for the file, in bytes.
    :>json int file.status: The :ref:`status <version-detail-status>` for the file.
    :>json string file.url: The (absolute) URL to download the file.
    :>json boolean is_disabled: If this version has been disabled by the developer. This field is only present for authenticated users, for their own add-ons.
    :>json object license: Object holding information about the license for the version.
    :>json boolean license.is_custom: Whether the license text has been provided by the developer, or not.  (When ``false`` the license is one of the common, predefined, licenses).
    :>json object|null license.name: The name of the license (See :ref:`translated fields <api-overview-translations>`).
    :>json object|null license.text: The text of the license (See :ref:`translated fields <api-overview-translations>`). For performance reasons this field is only present in version detail detail endpoint: all other endpoints omit it.
    :>json string|null license.url: The URL of the full text of license.
    :>json string|null license.slug: The license :ref:`slug <license-list>`, for non-custom (predefined) licenses.
    :>json object|null release_notes: The release notes for this version (See :ref:`translated fields <api-overview-translations>`).
    :>json string reviewed: The date the version was reviewed at.
    :>json boolean is_strict_compatibility_enabled: Whether or not this version has `strictCompatibility <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#strictCompatibility>`_. set.
    :>json string|null source: The (absolute) URL to download the submitted source for this version. This field is only present for authenticated users, for their own add-ons.
    :>json string version: The version number string for the version.


.. _version-detail-status:

    Possible values for the version/file ``status`` field / parameter:

    ==============  ==========================================================
             Value  Description
    ==============  ==========================================================
            public  Approved
          disabled  Rejected, disabled, or not reviewed
        unreviewed  Awaiting Review
    ==============  ==========================================================


--------------
Version Create
--------------

.. _version-create:

This endpoint allows a submission of an upload to an existing add-on to create a new version,
and setting other AMO metadata.

To create a listed version from an upload (an :ref:`upload <upload-create>` that
has channel == ``listed``) certain metadata must be defined - a version ``license``, an
add-on ``name``, an add-on ``summary``, and add-on categories for each app the version
is compatible with.  Add-on properties cannot be set with version create so an
:ref:`add-on update <addon-edit>` must be made beforehand if the properties are not
already defined.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/

    .. _version-create-request:

    :<json string approval_notes: Information for Mozilla reviewers, for when the add-on is reviewed.  These notes are only visible to Mozilla.
    :<json object|array compatibility:
        Either an object detailing which :ref:`applications <addon-detail-application>`
        and versions the version is compatible with; or an array of :ref:`applications <addon-detail-application>`,
        where min/max versions from the manifest, or defaults, will be used.  See :ref:`examples <version-compatibility-examples>`.
    :<json string compatibility[app_name].max: Maximum version of the corresponding app the version is compatible with. Should only be enforced by clients if ``is_strict_compatibility_enabled`` is ``true``.
    :<json string compatibility[app_name].min: Minimum version of the corresponding app the version is compatible with.
    :<json string license: The :ref:`slug of a non-custom license <license-list>`. The license must match the add-on type. Either provide ``license`` or ``custom_license``, not both.  If neither are provided, and there was a license defined for the previous version, it will inherit the previous version's license.
    :<json object|null custom_license.name: The name of the license (See :ref:`translated fields <api-overview-translations>`). Custom licenses are not supported for themes.
    :<json object|null custom_license.text: The text of the license (See :ref:`translated fields <api-overview-translations>`). Custom licenses are not supported for themes.
    :<json object|null release_notes: The release notes for this version (See :ref:`translated fields <api-overview-translations>`).
    :<json string|null source: The submitted source for this version. As JSON this field can only be set to null, to clear it - see :ref:`uploading source <version-sources>` to set/update the source file.
    :<json string upload: The uuid for the xpi upload to create this version with.


~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Version compatibility examples
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _version-compatibility-examples:

    .. note::
        The compatibility for Dictionary type add-ons cannot be created or updated.

Full example:

.. code-block:: json

    {
        "compatibility": {
            "android": {
                "min": "58.0a1",
                "max": "73.0"
            },
            "firefox": {
                "min": "58.0a1",
                "max": "73.0"
            }
        }
    }

With some versions omitted:

.. code-block:: javascript

    {
        "compatibility": {
            "android": {
                "min": "58.0a1"
                // "max" is undefined, so the manifest max or default will be used.
            },
            "firefox": {
                // the object is empty - both "min" and "max" are undefined so the manifest min/max
                // or defaults will be used.
            }
        }
    }

Shorthand, for when you only want to define compatible apps, but use the min/max versions from the manifest, or use all defaults:

.. code-block:: json

    {
        "compatibility": [
            "android",
            "firefox"
        ]
    }


~~~~~~~~~~~~~~~
Version Sources
~~~~~~~~~~~~~~~

.. _version-sources:

Version source files cannot be uploaded as JSON - the request must be sent as multipart form-data instead.
If desired, ``license`` can be set set/updated at the same time as ``source``, but fields that
contain complex data structure (list or object) such as ``compatibility``, ``release_notes``,
or ``custom_license`` can not, so separate API calls are needed.

Note: as form-data can not be nested as objects it's not possible to set ``source`` as part of the
``version`` object defined during an :ref:`Add-on create <addon-create>`.

.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/

    .. _version-sources-request-create:

    :form source: The add-on file being uploaded, or an empty value to clear.
    :form upload: The uuid for the xpi upload to create this version with.
    :form license: The :ref:`slug of a non-custom license <license-list>` (optional).
    :reqheader Content-Type: multipart/form-data


.. http:patch:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id|string:version_number)/

    .. _version-sources-request-edit:

    :form source: The add-on file being uploaded.
    :form license: The :ref:`slug of a non-custom license <license-list>` (optional).
    :reqheader Content-Type: multipart/form-data

------------
Version Edit
------------

.. _version-edit:

This endpoint allows the metadata for an existing version to be edited.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

    .. note::
        This API accepts both version ids and version numbers in the URL. If the version number passed does not contain any dot characters (``.``) it would be considered an ``id``. To avoid this and force a lookup by version number, add a ``v`` prefix to it.

.. http:patch:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id|string:version_number)/

    .. _version-edit-request:

    :<json string approval_notes: Information for Mozilla reviewers, for when the add-on is reviewed.  These notes are only visible to Mozilla.
    :<json object|array compatibility: Either an object detailing which :ref:`applications <addon-detail-application>` and versions the version is compatible with; or an array of :ref:`applications <addon-detail-application>`, where default min/max versions will be used if not already defined.  See :ref:`examples <version-compatibility-examples>`.
    :<json string compatibility[app_name].max: Maximum version of the corresponding app the version is compatible with. Should only be enforced by clients if ``is_strict_compatibility_enabled`` is ``true``.
    :<json string compatibility[app_name].min: Minimum version of the corresponding app the version is compatible with.
    :<json boolean is_disabled: If this version has been disabled by the developer. Note: a version with an already disabled file (``file.status`` is ``disabled``) cannot be changed to ``true``.
    :<json string license: The :ref:`slug of a non-custom license <license-list>`. The license must match the add-on type. Either provide ``license`` or ``custom_license``, not both.
    :<json object|null custom_license.name: The name of the license (See :ref:`translated fields <api-overview-translations>`). Custom licenses are not supported for themes.
    :<json object|null custom_license.text: The text of the license (See :ref:`translated fields <api-overview-translations>`). Custom licenses are not supported for themes.
    :<json object|null release_notes: The release notes for this version (See :ref:`translated fields <api-overview-translations>`).
    :<json string|null source: The submitted source for this version. As JSON this field can only be set to null, to clear it - see :ref:`uploading source <version-sources>` to set/update the source file.


--------------
Version Delete
--------------

.. _version-delete:

This endpoint allows a version to be deleted. The version will be soft-blocked (restricted), which will disable and prevent any further installation in Firefox. Existing users can choose to re-enable the add-on.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

    .. note::
        This API accepts both version ids and version numbers in the URL. If the version number passed does not contain any dot characters (``.``) it would be considered an ``id``. To avoid this and force a lookup by version number, add a ``v`` prefix to it.

.. http:delete:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id|string:version_number)/


----------------
Version Rollback
----------------

.. _version-rollback:

This endpoint allows an already approved version to be immediately re-created with a new version number, to rollback a problematic version.

The latest version in each channel is unavailable for rollback (or you wouldn't be rolling back anything); also, for listed channel, is limited to the previous approved version.
The rollback is asynchronous; you will be notified by email when it's complete (or failed).

See :ref:`version create <version-list>` - the second version in the list - for the listed version available for rollback.  Call the endpoint with ``?all_with_unlisted`` for all the unlisted versions, ignoring the first version and any versions that are not ``file.status == public``.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

    .. note::
        This API accepts both version ids and version numbers in the URL. If the version number passed does not contain any dot characters (``.``) it would be considered an ``id``. To avoid this and force a lookup by version number, add a ``v`` prefix to it.

    .. warning::
        For the listed channel, if there is a version awaiting review in the listed channel it will be disabled as part of the rollback.


.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id|string:version_number)/rollback/

    .. _version-rollback-request:

    :<json string new_version_string: The new version number (required).  It must be unique across all channels, and for listed versions, higher than all previously signed versions.
    :<json object|null release_notes: The release notes for this version (See :ref:`translated fields <api-overview-translations>`).


--------------
Preview Create
--------------

.. _addon-preview-create:

This endpoint allows a submission of a preview image to an existing non-theme add-on to create a new preview image. Themes can only have generated previews and new previews can not be created.
Image files cannot be uploaded as JSON - the request must be sent as multipart form-data instead.
If desired, ``position`` can be set set at the same time as ``image``, but ``caption`` can not, so a separate API call is needed.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

.. http:post:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/previews/

    .. _addon-preview-create-request:

    :form image: The image being uploaded.
    :form postion: Integer value for the position the image should be returned in the addon :ref:`detail <addon-detail-object>` (optional). Order is ascending so lower positions are placed earlier.
    :reqheader Content-Type: multipart/form-data


------------
Preview Edit
------------

.. _addon-preview-edit:

This endpoint allows the metadata for an existing preview for a non-theme add-on to be edited. Themes can only have generated previews and previews can not be edited.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

.. http:patch:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/previews/(int:id)/

    .. _addon-preview-edit-request:

    :<json object caption: The caption describing a preview (See :ref:`translated fields <api-overview-translations>`).
    :<json int position: The position the image should be returned in the addon :ref:`detail <addon-detail-object>`. Order is ascending so lower positions are placed earlier.


--------------
Preview Delete
--------------

.. _addon-preview-delete:

This endpoint allows the metadata for an existing preview for a non-theme add-on to be deleted. Themes can only have generated previews and previews can not be deleted.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

.. http:delete:: /api/v5/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/previews/(int:id)/


-------------
Upload Create
-------------

.. _upload-create:

This endpoint is for uploading an addon file, to then be submitted to create a new addon or version.

    .. note::
        This API requires :doc:`authentication <auth>`.

.. http:post:: /api/v5/addons/upload/

    .. _upload-create-request:

    :form upload: The add-on file being uploaded.
    :form channel: The channel this version should be uploaded to, which determines its visibility on the site. It can be either ``unlisted`` or ``listed``.
    :reqheader Content-Type: multipart/form-data


After the file has uploaded the :ref:`upload response <upload-detail-object>` will be
returned immediately, and the addon submitted for validation.
The :ref:`upload detail endpoint <upload-detail>` should be queried for validation status
to determine when/if the upload can be used to create an add-on/version.


-----------
Upload List
-----------

.. _upload-list:

This endpoint is for listing your previous uploads.

    .. note::
        This API requires :doc:`authentication <auth>`.

.. http:get:: /api/v5/addons/upload/

    :query int page: 1-based page number. Defaults to 1.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :>json int count: The number of uploads this user has submitted.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`uploads <upload-detail-object>`.


-------------
Upload Detail
-------------

.. _upload-detail:

This endpoint is for fetching a single previous upload by uuid.

    .. note::
        This API requires :doc:`authentication <auth>`.

.. http:get:: /api/v5/addons/upload/<string:uuid>/

    .. _upload-detail-object:

    :>json string uuid: The upload id.
    :>json string channel: The version channel, which determines its visibility on the site. Can be either ``unlisted`` or ``listed``.
    :>json boolean processed: If the version has been processed by the validator.
    :>json boolean submitted: If this upload has been submitted as a new add-on or version already. An upload can only be submitted once.
    :>json string url: URL to check the status of this upload.
    :>json boolean valid: If the version passed validation.
    :>json object validation: the validation results JSON blob.
    :>json string version: The version number parsed from the manifest.


-----------------------
EULA and Privacy Policy
-----------------------

.. _addon-eula-policy:

This endpoint allows you to fetch an add-on EULA and privacy policy.

.. http:get:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/eula_policy/

    .. note::
        Non-public add-ons and add-ons with only unlisted versions require both:

            * authentication
            * reviewer permissions or an account listed as a developer of the add-on

    :>json object|null eula: The text of the EULA, if present (See :ref:`translated fields <api-overview-translations>`).
    :>json object|null privacy_policy: The text of the Privacy Policy, if present (See :ref:`translated fields <api-overview-translations>`).


----------------------------
EULA and Privacy Policy Edit
----------------------------

.. _addon-eula-policy-edit:

This endpoint allows an add-on's EULA and privacy policy to be edited.

    .. note::
        This API requires :doc:`authentication <auth>`, and for the user to be an author of the add-on.

    .. note::
        This API is not valid for themes - themes do not have EULA or privacy policies.

.. http:patch:: /api/v5/addons/addon/(int:id|string:slug|string:guid)/eula_policy/

    :<json object|null eula: The EULA text (See :ref:`translated fields <api-overview-translations>`).
    :<json object|null privacy_policy: The privacy policy text (See :ref:`translated fields <api-overview-translations>`).


--------------
Language Tools
--------------

.. _addon-language-tools:

This endpoint allows you to list all public language tools add-ons available
on AMO.

.. http:get:: /api/v5/addons/language-tools/

    .. note::
        Because this endpoint is intended to be used to feed a page that
        displays all available language tools in a single page, it is not
        paginated as normal, and instead will return all results without
        obeying regular pagination parameters. The ordering is left undefined,
        it's up to the clients to re-order results as needed before displaying
        the add-ons to the end-users.

        In addition, the results can be cached for up to 24 hours, based on the
        full URL used in the request.

    :query string app: Mandatory when ``appversion`` is present, ignored otherwise. Filter by :ref:`add-on application <addon-detail-application>` availability.
    :query string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when both the ``app`` and ``type`` parameters are also present, and only makes sense for Language Packs, since Dictionaries are always compatible with every application version.
    :query string author: Filter by exact (listed) author username. Multiple author names can be specified, separated by comma(s), in which case add-ons with at least one matching author are returned.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string type: Mandatory when ``appversion`` is present. Filter by :ref:`add-on type <addon-detail-type>`. The default is to return both Language Packs or Dictionaries.
    :>json array results: An array of language tools.
    :>json int results[].id: The add-on id on AMO.
    :>json object results[].current_compatible_version: Object holding the latest publicly available :ref:`version <version-detail-object>` of the add-on compatible with the ``appversion`` parameter used. Only present when ``appversion`` is passed and valid. For performance reasons, only the following version properties are returned on the object: ``id``, ``file``, ``reviewed``, and ``version``.
    :>json string results[].default_locale: The add-on default locale for translations.
    :>json object|null results[].name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :>json string results[].guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json string results[].slug: The add-on slug.
    :>json string results[].target_locale: For dictionaries and language packs, the locale the add-on is meant for. Only present when using the Language Tools endpoint.
    :>json string results[].type: The :ref:`add-on type <addon-detail-type>`.
    :>json string results[].url: The (absolute) add-on detail URL.


-------------------
Replacement Add-ons
-------------------

.. _addon-replacement-addons:

This endpoint returns a list of suggested replacements for legacy add-ons that are unsupported in Firefox 57.

.. http:get:: /api/v5/addons/replacement-addon/

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

.. _addon-recommendations:

This endpoint provides recommendations of other addons to install. Maximum four recommendations will be returned.

.. http:get:: /api/v5/addons/recommendations/

    :query string app: Set the :ref:`add-on application <addon-detail-application>` for that query. This won't filter the results. Defaults to ``firefox``.
    :query string guid: Fetch recommendations for this add-on guid.
    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query boolean recommended: Ignored.
    :>json string outcome: Outcome of the response returned. Will always be ``curated``.
    :>json null fallback_reason: Always null.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`. The following fields are omitted for performance reasons: ``release_notes`` and ``license`` fields on ``current_version`` and ``current_beta_version``, as well as ``picture_url`` from ``authors``.


----------------
Browser Mappings
----------------

.. _addon-browser-mappings:

This endpoint provides browser mappings of non-Firefox and Firefox extensions.  Added to support the extensions import feature in Firefox.

.. http:get:: /api/v5/addons/browser-mappings/

    .. note::
        This endpoint uses a larger ``page_size`` than most other API endpoints.

    :query string browser: The browser identifier for this query (required). Must be one of these: ``chrome``.
    :query int page_size: Maximum number of results to return for the requested page. Defaults to 100.
    :>json array results: An array containing a mapping of non-Firefox and Firefox extension IDs for a given browser.
    :>json string results[].extension_id: A non-Firefox extension ID.
    :>json string results[].addon_guid: The corresponding Firefox add-on ``guid``.
