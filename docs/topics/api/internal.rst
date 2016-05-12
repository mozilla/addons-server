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

.. _addon-search:

This endpoint allows you to search through all add-ons. It's similar to the
:ref:`regular add-on search API <addon-search>`, but is not limited to public
add-ons, and can return disabled, unreviewer, unlisted or even deleted add-ons.

.. note::
    Requires authentication and `AdminTools::View` or `ReviewerAdminTools::View`
    permissions.

.. http:get:: /api/v3/internal/addons/search/

    :param string q: The search query.
    :param string app: Filter by add-on application availability. Supported values: ``firefox``, ``thunderbird``, ``seamonkey``, ``sunbird``, ``android``.
    :param string appversion: Filter by application version compatibility. Pass the full version as a string, e.g. ``46.0``. Only valid when the ``app`` parameter is also present.
    :param string platform: Filter by add-on platform availability. Supported values: ``linux``, ``mac``, ``windows``, ``android``.
    :param string type: Filter by add-on type. Supported values: ``dictionary``, ``extension``, ``language`` (language packs), ``persona`` (lightweight themes), ``search`` (search plugins), ``theme`` (complete themes).
    :param string status: Filter by add-on status. Supported values: ``beta``, ``blocked``, ``deleted``, ``disabled``, ``incomplete``, ``lite``, ``lite-nominated``, ``nominated``, ``pending``, ``public``, ``purgatory``, ``rejected``, ``review-pending``, ``unreviewed``.
    :param string sort: The sort parameter. See :ref:`add-on search sorting parameters <addon-search-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`.

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
