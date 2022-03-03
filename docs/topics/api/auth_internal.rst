.. _api-auth-internal:

=========================
Authentication (internal)
=========================

This documents how to use authentication in your API requests when you are
working on a web application that lives on AMO domain or subdomain. If you
are looking for how to authenticate with the API from an external client, using
your API keys, read the :ref:`documentation for external authentication
<api-auth>` instead.

When using this authentication mechanism, the server creates a session and stores the
session id in the ``sessionid`` cookie when the user logs in.
The client must then include that session id in an ``Authorization`` header on requests
that need authentication.
The clients never generate tokens or sessions themselves.

Creating a session
==================

A session, valid for 30 days, is automatically generated when a log in via Firefox Accounts
has completed, and the user is redirected back to the following endpoint:

    * ``/api/auth/authenticate-callback/``

The session id is then available in a cookie called ``sessionid``. This cookie expires
after 30 days and is set as ``HttpOnly``.


Creating an Authorization header
================================

When making an authenticated API request, put the session id from the cookie into an
HTTP Authorization header prefixed with ``Session``, like this::

    Authorization: Session 1234567890


========================
FxA Notification Webhook
========================

To integrate with Firefox Account's `webhook <https://mozilla.github.io/ecosystem-platform/platform/firefox-accounts/integration-with-fxa#webhook-events>`_
the following endpoint is available:

``/api/auth/fxa-notification/``

Authentication is accomplished by decoding using the known `JWT keys available` <https://oauth.accounts.firefox.com/v1/jwks>`_
- normal AMO authentication is not used.

This endpoint is not usable for anything other than AMOs internal integration with Firefox Accounts.
