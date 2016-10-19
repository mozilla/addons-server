========
Internal
========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

-------------
Add-on Search
-------------

.. _internal-addon-search:

This endpoint allows you to search through all add-ons. It's similar to the
:ref:`regular add-on search API <addon-search>`, but is not limited to public
add-ons, and can return disabled, unreviewer, unlisted or even deleted add-ons.

.. note::
    Requires authentication and `AdminTools::View` or `ReviewerAdminTools::View`
    permissions.

.. http:get:: /api/v3/internal/addons/search/

    :param string q: The search query.
    :param string app: Filter by :ref:`add-on application <addon-detail-application>` availability.
    :param string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :param string platform: Filter by :ref:`add-on platform <addon-detail-platform>` availability.
    :param string type: Filter by :ref:`add-on type <addon-detail-type>`.
    :param string status: Filter by :ref:`add-on status <addon-detail-status>`.
    :param string sort: The sort parameter. See :ref:`add-on search sorting parameters <addon-search-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`.

-------------
Add-on Detail
-------------

.. _internal-addon-detail:

This endpoint allows you to retrieve the details of an add-on. It is the same
as the :ref:`regular add-on detail API <addon-detail>`, but that endpoint may
have its scope reduced to public add-ons and add-ons you own in the future. If
you need to access add-ons you do not own or that have been deleted and you
have sufficient permissions use this endpoint.

    .. note::
        Unlisted or non-public add-ons require authentication and either
        reviewer permissions or a user account listed as a developer of the
        add-on.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/

    .. _addon-detail-object:

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :>json int id: The add-on id on AMO.
    :>json array authors: Array holding information about the authors for the add-on.
    :>json int authors[].id: The id for an author.
    :>json string authors[].name: The name for an author.
    :>json string authors[].url: The link to the profile page for an author.
    :>json int average_daily_users: The average number of users for the add-on per day.
    :>json object categories: Object holding the categories the add-on belongs to.
    :>json array categories[app_name]: Array holding the :ref:`category slugs <category-list>` the add-on belongs to for a given :ref:`add-on application <addon-detail-application>`. (Combine with the add-on ``type`` to determine the name of the category).
    :>json object compatibility: Object detailing the add-on :ref:`add-on application <addon-detail-application>` and version compatibility.
    :>json object compatibility[app_name].max: Maximum version of the corresponding app the add-on is compatible with.
    :>json object compatibility[app_name].min: Minimum version of the corresponding app the add-on is compatible with.
    :>json object current_beta_version: Object holding the current beta :ref:`version <version-detail-object>` of the add-on, if it exists. For performance reasons the ``license`` and ``release_notes`` fields are omitted.
    :>json object current_version: Object holding the current :ref:`version <version-detail-object>` of the add-on. For performance reasons the ``license`` and ``release_notes`` fields are omitted.
    :>json string default_locale: The add-on default locale for translations.
    :>json string|object|null description: The add-on description (See :ref:`translated fields <api-overview-translations>`).
    :>json string edit_url: The URL to the developer edit page for the add-on.
    :>json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :>json boolean has_eula: The add-on has an End-User License Agreement that the user needs to agree with before installing (See :ref:`add-on EULA and privacy policy <addon-eula-policy>`).
    :>json boolean has_privacy_policy: The add-on has a Privacy Policy (See :ref:`add-on EULA and privacy policy <addon-eula-policy>`).
    :>json string|object|null homepage: The add-on homepage (See :ref:`translated fields <api-overview-translations>`).
    :>json string icon_url: The URL to icon for the add-on (including a cachebusting query string).
    :>json boolean is_disabled: Whether the add-on is disabled or not.
    :>json boolean is_experimental: Whether the add-on has been marked by the developer as experimental or not.
    :>json boolean is_listed: Whether the add-on is listed or not.
    :>json boolean is_source_public: Whether the add-on source is publicly viewable or not.
    :>json string|object|null name: The add-on name (See :ref:`translated fields <api-overview-translations>`).
    :>json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json array previews: Array holding information about the previews for the add-on.
    :>json int previews[].id: The id for a preview.
    :>json string|object|null previews[].caption: The caption describing a preview (See :ref:`translated fields <api-overview-translations>`).
    :>json string previews[].image_url: The URL (including a cachebusting query string) to the preview image.
    :>json string previews[].thumbnail_url: The URL (including a cachebusting query string) to the preview image thumbnail.
    :>json boolean public_stats: Boolean indicating whether the add-on stats are public or not.
    :>json object ratings: Object holding ratings summary information about the add-on.
    :>json int ratings.count: The number of user ratings for the add-on.
    :>json float ratings.average: The average user rating for the add-on.
    :>json string review_url: The URL to the review page for the add-on.
    :>json string slug: The add-on slug.
    :>json string status: The :ref:`add-on status <addon-detail-status>`.
    :>json string|object|null summary: The add-on summary (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null support_email: The add-on support email (See :ref:`translated fields <api-overview-translations>`).
    :>json string|object|null support_url: The add-on support URL (See :ref:`translated fields <api-overview-translations>`).
    :>json array tags: List containing the text of the tags set on the add-on.
    :>json object theme_data: Object holding `lightweight theme (Persona) <https://developer.mozilla.org/en-US/Add-ons/Themes/Lightweight_themes>`_ data. Only present for themes (Persona).
    :>json string type: The :ref:`add-on type <addon-detail-type>`.
    :>json string url: The (absolute) add-on detail URL.
    :>json int weekly_downloads: The number of downloads for the add-on per week.

-----------------------
Internal Login JSON API
-----------------------

.. _internal-login-json-api:

The JSON API login flow is initiated by accessing the start endpoint which
will add an ``fxa_state`` to the user's session and redirect them to Firefox
Accounts. When the user finishes authenticating with Firefox Accounts they
will be redirected to the client application which can make a request to the
login endpoint to exchange the Firefox Accounts token and state for a JWT.

.. http:get:: /api/v3/internal/accounts/login/start/

    :param string to: A path to append to the state. The state will be returned
        from FxA as ``state:path``, the path will be URL safe base64 encoded.
    :status 302: Redirect user to Firefox Accounts.
