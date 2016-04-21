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
creating a `JSON Web Token (JWT)`_ when the user logs in, and sends it back in
the response. The clients must then include that token as an ``Authorization``
header on requests that need authentication. The clients never generate JWTs
themselves.

Fetching the JWT
================

A fresh JWT, valid for 30 days, is automatically generated and added to the
responses of the following endpoints:

    * ``/api/v3/accounts/login/``
    * ``/api/v3/accounts/register/``
    * ``/api/v3/accounts/authenticate/``

A JWT may also be obtained through the JSON API as outlined in the
:ref:`internal login JSON API <internal-login-json-api>` section. This is only
accessible through the VPN and requires using the following endpoints:

    * ``/api/v3/internal/accounts/login/start/``
    * ``/api/v3/internal/accounts/login/``

The token is available in two forms:

    * For the endpoints returning JSON, as a property called ``token``.
    * For all endpoints, as a cookie called ``jwt_api_auth_token``. This cookie
      expires after 30 days and is set as ``HttpOnly``.


Verifying a JWT
===============

You can verify that a token is valid by calling:

.. http:post:: /api/v3/frontend-token/verify/

    :<json string token: The JWT you want to verify.
    :status 200: The token is valid.
    :status 400: The token is invalid.

If a 400 Bad Request error is returned, the body of the response may contain
additional information explaining why the token is invalid.


Creating an Authorization header
================================

When making an authenticated API request, put your generated
`JSON Web Token (JWT)`_ into an HTTP Authorization header prefixed with
``Bearer``, like this::

    Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE0NDcyNzMwOTZ9.MG9LJiEK5_Db8WpF5cWWRebXCtUB48EJzxKIBqQhSOo


.. _`jwt-spec`: https://tools.ietf.org/html/rfc7519
.. _`JSON Web Token (JWT)`: jwt-spec_
