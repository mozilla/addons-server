.. _api:

======================
Marketplace API
======================

This API is for Apps. There is a separate set of `APIs for Add-ons`_.

.. toctree::
   :maxdepth: 2

   api/submission.rst
   api/payment.rst
   api/search.rst
   api/misc.rst

Authentication
==============

Not all APIs require authentication. Each API will note if it needs
authentication.

Currently only two legged OAuth authentication is supported. This is focused on
clients who would like to create multiple apps on the app store from an end
point.

When you are first developing your API to communicate with the Marketplace, you
should use the development server to test your API. When it's complete, you can
request a production token.

Development server
++++++++++++++++++

The development server is at https://marketplace-dev.allizom.org.

We make no guarantees on the uptime of the development server. Data is
regularly purged, causing the deletion of apps and tokens.

1. Login to the development server using Persona:
   https://marketplace-dev.allizom.org/login

2. Once logged in, read and accept the terms of service for the Marketplace
   at: https://marketplace-dev.allizom.org/developers/terms

3. Generate a new key at: https://marketplace-dev.allizom.org/developers/api

Production server
+++++++++++++++++

The production server is at https://marketplace.firefox.com.

1. Login to the production server using Persona:
   https://marketplace.firefox.com

2. Once logged in, read and accept the terms of service for the Marketplace
   at: https://marketplace.firefox.com/developers/terms

3. You cannot generate your own tokens. Please contact a `Marketplace
   representative`_.

Using OAuth Tokens
++++++++++++++++++

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
a reason contained in the response. For example::

        {u'reason': u'Terms of service not accepted.'}

Requests
========

All requests should be made with the header::

        Content-type: application/json

If you access the URLs in this document in a browser, then prepend
`?format=json` on to the request.

Verbs
+++++

This follows the order of the `django-tastypie`_ REST verbs, a PUT for an
update and POST for create.


Responses
=========

For purposes of brevity in the documentation, irrelevant parts of the responses
will be shown with ellipses (...).

Marketplace will return errors as JSON with the appropriate status code.

Data errors
+++++++++++

If there is an error in your data, a 400 status code will be returned. There
can be multiple errors per field. Example::

        {
          "error_message": {
            "manifest": ["This field is required."]
          }
        }

Other errors
++++++++++++

The appropriate HTTP status code will be returned.

Content-type
++++++++++++

All responses are in JSON.

.. _`MDN`: https://developer.mozilla.org
.. _`Marketplace representative`: marketplace-team@mozilla.org
.. _`django-tastypie`: https://github.com/toastdriven/django-tastypie
.. _`APIs for Add-ons`: https://developer.mozilla.org/en/addons.mozilla.org_%28AMO%29_API_Developers%27_Guide
.. _`example marketplace client`: https://github.com/mozilla/Marketplace.Python
