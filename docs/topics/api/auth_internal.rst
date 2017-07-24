.. _api-auth-internal:

=========================
Authentication (internal)
=========================

This documents how to use authentication in your API requests when you are
working on a web application that lives on AMO domain or subdomain. If you
are looking for how to authenticate with the API from an external client, using
your API keys, read the :ref:`documentation for external authentication
<api-auth>` instead.

When using this authentication mechanism, the server is responsible for
creating an API Token when the user logs in, and sends it back in
the response. The clients must then include that token as an ``Authorization``
header on requests that need authentication. The clients never generate JWTs
themselves.

Fetching the token
==================

A fresh token, valid for 30 days, is automatically generated and added to the
responses of the following endpoints:

    * ``/api/v3/accounts/login/``
    * ``/api/v3/accounts/register/``
    * ``/api/v3/accounts/authenticate/``

A token may also be obtained through the JSON API as outlined in the
:ref:`internal login JSON API <internal-login-json-api>` section. This is only
accessible through the VPN and requires using the following endpoints:

    * ``/api/v3/internal/accounts/login/start/``
    * ``/api/v3/internal/accounts/login/``

The token is available in two forms:

    * For the endpoints mentionned above, as a property called ``token``.
    * For all endpoints, as a cookie called ``api_auth_token``. This cookie
      expires after 30 days and is set as ``HttpOnly``.

The response will contain some profile data for personalization:

.. http:get:: /api/v3/accounts/login/

    :>json int id: The numeric user id.
    :>json string email: Email address used by the user to log in and create this account.
    :>json string name: The name chosen by the user, or the username if not set.
    :>json string picture_url: URL to a photo of the user, or `/static/img/anon_user.png` if not set.
    :>json string username: username chosen by the user, used in the account url. If not set will be a randomly generated string.
    :>json array permissions: A list of the additional :ref:`permissions <login-response-permissions>` this user has.

.. _login-response-permissions:

    Permissions can be any arbritary string in the format `app:action`. Either `app` or `action` can be
    the wildcard `*`, so `*:*` means the user has permission to do all actions (i.e. full admin).

    The following are some commonly tested permissions; see https://github.com/mozilla/addons-server/blob/master/src/olympia/constants/permissions.py
    for the full list.

    ==================  ==========================================================
                 Value  Description
    ==================  ==========================================================
     `AdminTools:View`  Can access the website admin interface index page.  Inner
                        pages may require other/additional permissions.
         `Addons:Edit`  Allows viewing and editing of any add-ons details in
                        developer tools.
       `Addons:Review`  Can access the add-on reviewer tools to approve/reject
                        add-on submissions.
     `Personas:Review`  Can access the theme reviewer tools to approve/reject
                        theme submissions.
    ==================  ==========================================================


Creating an Authorization header
================================

When making an authenticated API request, put your generated API Token into an
HTTP Authorization header prefixed with ``Bearer``, like this::

    Authorization: Bearer eyJhdXRoX2hhc2giOiJiY2E0MTZkN2RiMGU3NjFmYTA2NDE4MjAzZWU1NTMwOTM4OGZhNzcxIiwidXNlcl9pZCI6MTIzNDV9:1cqe2Q:cPMlmz8ejIkutD-gNo3EWU8IfL8
