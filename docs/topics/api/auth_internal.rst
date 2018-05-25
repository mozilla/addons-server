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
responses of the following endpoint:

    * ``/api/v4/accounts/authenticate/``

The token is available in two forms:

    * For the endpoint mentioned above, as a property called ``token``.
    * For all endpoints, as a cookie called ``frontend_auth_token``. This cookie
      expires after 30 days and is set as ``HttpOnly``.


Creating an Authorization header
================================

When making an authenticated API request, put your generated API Token into an
HTTP Authorization header prefixed with ``Bearer``, like this::

    Authorization: Bearer eyJhdXRoX2hhc2giOiJiY2E0MTZkN2RiMGU3NjFmYTA2NDE4MjAzZWU1NTMwOTM4OGZhNzcxIiwidXNlcl9pZCI6MTIzNDV9:1cqe2Q:cPMlmz8ejIkutD-gNo3EWU8IfL8
