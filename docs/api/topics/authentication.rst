.. _authentication:

==============
Authentication
==============

Not all APIs require authentication. Each API will note if it needs
authentication.

Two options for authentication are available: shared-secret and OAuth.

Shared Secret
=============

The Marketplace frontend uses a server-supplied token for authentication,
stored as a cookie.

.. http:post:: /api/v1/account/login/

    **Request**

    :param assertion: the Persona assertion.
    :param audience: the Persona audience.

    Example:

    .. code-block:: json

        {
            "assertion": "1234",
            "audience": "some.site.com"
        }

    **Response**

    :param string error: any error that occurred.
    :param string token: a shared secret to be used on later requests. It should be
        sent with authorized requests as a query string parameter named
        ``_user``.
    :param object permissions: :ref:`user permissions <permission-get-label>`.
    :param object settings: user account settings.

    Example:

    .. code-block:: json

        {
            "error": null,
            "token": "ffoob@example.com,95c9063d9f249aacfe5697fc83192e...",
            "settings": {
                "display_name": "fred foobar",
                "email": "ffoob@example.com",
                "region": "appistan"
            },
            "permissions": {
                "reviewer": false,
                "admin": false,
                "localizer": false,
                "lookup": true,
                "developer": true
            }
        }

OAuth
=====

Marketplace provides OAuth 1.0a, allowing third-party apps to interact with its
API.

When you are first developing your API to communicate with the Marketplace, you
should use the development server to test your API.

Production server
=================

The production server is at https://marketplace.firefox.com.

1. Log in using Persona:
   https://marketplace.firefox.com/login

2. At https://marketplace.firefox.com/developers/api provide the name of
   the app that will use the key, and the URI that Marketplace's OAuth provide
   will redirect to after the user grants permission to your app. You may then
   generate a key pair for use in your application.

3. (Optional) If you are planning on submitting an app, you must accept the
   terms of service: https://marketplace.firefox.com/developers/terms

Development server
==================

The development server is at https://marketplace-dev.allizom.org.

We make no guarantees on the uptime of the development server. Data is
regularly purged, causing the deletion of apps and tokens.

Using OAuth Tokens
==================

Once you've got your token, you will need to ensure that the OAuth token is
sent correctly in each request.

To correctly sign an OAuth request, you'll need the OAuth consumer key and
secret and then sign the request using your favourite OAuth library. An example
of this can be found in the `example marketplace client`_.

Example headers (new lines added for clarity)::

        Content-type: application/json
        Authorization: OAuth realm="",
                       oauth_body_hash="2jm...",
                       oauth_nonce="06731830",
                       oauth_timestamp="1344897064",
                       oauth_consumer_key="some-consumer-key",
                       oauth_signature_method="HMAC-SHA1",
                       oauth_version="1.0",
                       oauth_signature="Nb8..."

If requests are failing and returning a 401 response, then there will likely be
a reason contained in the response. For example:

        .. code-block:: json

            {"reason": "Terms of service not accepted."}

.. _`example marketplace client`: https://github.com/mozilla/Marketplace.Python
