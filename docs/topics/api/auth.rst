.. _api-auth:

================
Authentication
================

To access the API, you need to include a `JSON Web Token (JWT)`_
in an authorization header for every request. This header authenticates
your user account so you could think of it like a session cookie.

Access Credentials
==================

To create JWTs, first obtain a **key** and **secret** from the
`API Credentials Management Page`_.
Keep the secret string well protected and never check it into version control.
If someone obtains your secret they can make API requests on behalf of your
user account.

Create a JWT for each request
=============================

Prior to making every API request, you need to generate a fresh `JWT`_.
The JWT will have a short expiration time and is only valid for a single
request so you can't cache or reuse it.
You only need to include a few standard fields; here's what the raw JSON object
needs to look like before it's signed:

.. code-block:: json

    {
        "iss": "your-api-key",
        "jti": "0.47362944623455405",
        "iat": 1447273096,
        "exp": 1447273156
    }

iss
    This is a `standard JWT claim`_ identifying
    the *issuer*. Set this to the **API key** you generated on the
    `credentials management page`_.
    For example: ``user:543210:23``.
jti
    This is a `standard JWT claim`_ declaring a *JWT ID*.
    This value needs to have a high probability of being unique across all
    recent requests made by your issuer ID. This value is a type of
    `cryptographic nonce <https://en.wikipedia.org/wiki/Cryptographic_nonce>`_
    designed to prevent
    `replay attacks <https://en.wikipedia.org/wiki/Replay_attack>`_.
iat
    This is a `standard JWT claim`_ indicating
    the *issued at time*. It should be a Unix epoch timestamp and
    **must be in UTC time**.
exp
    This is a `standard JWT claim`_ indicating
    the *expiration time*. It should be a Unix epoch timestamp in UTC time
    and must be **no longer than 60 seconds** past the issued at time.

.. note::
    If you're having trouble authenticating, make sure your system
    clock is correct and consider synchronizing it with something like
    `NTP (Network Time Protocol) <http://www.ntp.org/>`_.

Take this JSON object and sign it with the **API secret** you generated on the
`credentials management page`_. You must sign the JWT using the ``HMAC-SHA256``
algorithm (which is typically the default).
The final JWT will be a blob of base64 encoded text, something like::

    eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE0NDcyNzMwOTZ9.MG9LJiEK5_Db8WpF5cWWRebXCtUB48EJzxKIBqQhSOo

Here is an example of creating a JWT in `NodeJS <https://nodejs.org/en/>`_
using the `node-jsonwebtoken <https://github.com/auth0/node-jsonwebtoken>`_
library:

.. code-block:: javascript

    var jwt = require('jsonwebtoken');

    var issuedAt = Math.floor(Date.now() / 1000);
    var payload = {
      iss: 'your-api-key',
      jti: Math.random().toString(),
      iat: issuedAt,
      exp: issuedAt + 60,
    };

    var secret = 'your-api-secret';  // store this securely.
    var token = jwt.sign(payload, secret, {
      algorithm: 'HS256',  // HMAC-SHA256 signing algorithm
    });

Create an Authorization header
==============================

When making each request, put your generated `JSON Web Token (JWT)`_
into an HTTP Authorization header prefixed with ``JWT``, like this::

    Authorization: JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE0NDcyNzMwOTZ9.MG9LJiEK5_Db8WpF5cWWRebXCtUB48EJzxKIBqQhSOo

Example request
===============

Using the :ref:`upload status check <version-status>` as an example endpoint,
here's what a JWT authenticated HTTP request would look like in
`curl <http://curl.haxx.se/>`_::

    curl https://addons.mozilla.org/api/v3/addons/some-id/versions/0.0.1/ \
         -H 'Authorization: JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE0NDcyNzMwOTZ9.MG9LJiEK5_Db8WpF5cWWRebXCtUB48EJzxKIBqQhSOo'


Find a JWT library
==================

There are robust open source libraries for creating JWTs in
`all major programming languages <http://jwt.io/>`_.

.. _`manage-credentials`: https://addons.mozilla.org/en-US/developers/addon/api/key/
.. _`API Credentials Management Page`: manage-credentials_
.. _`credentials management page`: manage-credentials_
.. _`jwt-spec`: https://tools.ietf.org/html/rfc7519
.. _JWT: jwt-spec_
.. _`JSON Web Token (JWT)`: jwt-spec_
.. _`standard JWT claim`: jwt-spec_
