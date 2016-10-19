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
