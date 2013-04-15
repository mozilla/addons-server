.. _api:

======================
Marketplace API
======================

This API is for Apps. There is a separate set of `APIs for Add-ons`_.

.. toctree::
   :maxdepth: 2

   topics/submission.rst
   topics/payment.rst
   topics/search.rst
   topics/ratings.rst
   topics/misc.rst
   topics/reviewers.rst

Versioning
==========

This API is versioned and we are currently moving towards version 1 of the API.
The API will be versioned by the URL, so that version 1 APIs will all be at::

    /api/v1/...

If you are not using the most recent version of the API then you will get
a header in the response::

    X-API-Status: Deprecated

The current policy for how long deprecated APIs will exist has not been
defined, but it would include time for any clients to upgrade before versions
are turned off.

We will also return the version of the API we think you are using::

    X-API-Version: 1

.. note: Before v1 is released, the API was unversioned at `/api/v1/`, because
    of the small number of clients using that URL, we hope all users are able to
    update to `/api/v1/` quickly so we can remove that unversioned URL.

Authentication
==============

Not all APIs require authentication. Each API will note if it needs
authentication.

Two options for authentication are available: shared-secret and OAuth.

Shared Secret
+++++++++++++

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

    :param error: any error that occurred.
    :param token: a shared secret to be used on later requests. It should be
        sent with authorized requests as a query string parameter named
        ``_user``.
    :param settings: user account settings.

    Example:

    .. code-block:: json

        {
            "error": null,
            "token": "ffoob@example.com,95c9063d9f249aacfe5697fc83192e...",
            "settings": {
                "display_name": "fred foobar",
                "email": "ffoob@example.com",
                "region": "appistan"
            }
        }

OAuth
+++++

Currently only two legged OAuth authentication is supported. This is focused on
clients who would like to create multiple apps on the app store from an end
point.

When you are first developing your API to communicate with the Marketplace, you
should use the development server to test your API. When it's complete, you can
request a production token.

Development server
~~~~~~~~~~~~~~~~~~

The development server is at https://marketplace-dev.allizom.org.

We make no guarantees on the uptime of the development server. Data is
regularly purged, causing the deletion of apps and tokens.

1. Login to the development server using Persona:
   https://marketplace-dev.allizom.org/login

2. Once logged in, read and accept the terms of service for the Marketplace
   at: https://marketplace-dev.allizom.org/developers/terms

3. Generate a new key at: https://marketplace-dev.allizom.org/developers/api

Production server
~~~~~~~~~~~~~~~~~

The production server is at https://marketplace.firefox.com.

1. Login to the production server using Persona:
   https://marketplace.firefox.com

2. Once logged in, read and accept the terms of service for the Marketplace
   at: https://marketplace.firefox.com/developers/terms

3. You cannot generate your own tokens. Please contact a `Marketplace
   representative`_.

Using OAuth Tokens
~~~~~~~~~~~~~~~~~~

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

Requests
========

All requests should be made with the header::

        Content-type: application/json

If you access the URLs in this document in a browser, then prepend
`?format=json` on to the request.

Verbs
+++++

This follows the order of the `django-tastypie`_ REST verbs.

* ``GET`` gets an individual resource or listing.
* ``POST`` creates a resource.
* ``PUT`` replaces a resource, so this alters all the data on an existing
  resource.
* ``PATCH`` alters some parts of an existing resource.
* ``DELETE`` deletes an object.

A ``GET`` that accesses a standard listing object, also accepts the parameters
in the query string for filtering the result set down.

A ``POST``, ``PUT`` and ``PATCH`` accept parameters as either:

* a JSON document in the body of the request, if so the `Content-Type` must be
  set to `application\json` or
* form urlencoded values in the body of the request, if so the `Content-Type`
  must be set to `application/x-www-form-urlencoded`

If you are unable to make the correct kind of request, you send a request using
any verb with the header ``X-HTTP-METHOD-OVERRIDE`` containing the verb you
would like to use.

Responses
=========

Because the responses can be quite long, rather than show the full result, we
link to examples of the results.  All responses are in JSON. The client must
send either no HTTP `Accept` header, or a value of `application\json`. Any
other value will result in 400 status code.

Data errors
+++++++++++

If there is an error in your data, a 400 status code will be returned. There
can be multiple errors per field. Example:

    .. code-block:: json

        {
            "error_message": {
                "manifest": ["This field is required."]
            }
        }

Rate limiting
+++++++++++++

Select API endpoints are rate-limited. When an application exceeds the rate
limit for a given endpoint, the API will return an HTTP 429 response.

Other errors
++++++++++++

The appropriate HTTP status code will be returned, with the error in JSON.

Listings
++++++++

When an API returns a list of objects, it will generally return a response in
the same manner every time. There are a few exceptions for specialised API's
and these are noted.

A listing API will return a two elements, meta and objects. Rather than include
this output in all the API docs, we will link to these documents or the
relevant object.

.. _meta-response-label:

Listing response meta
~~~~~~~~~~~~~~~~~~~~~

This is information about the object listing so that the client can paginate
through the listing with. For example:

    .. code-block:: json

        {
            "meta": {
                "limit": 3,
                "next": "/api/v1/apps/category/?limit=3&offset=6",
                "offset": 3,
                "previous": "/api/v1/apps/category/?limit=3&offset=0",
                "total_count": 16
            }
        }

To support the listing, the following query params can be passed through to any
listing page.

.. _list-query-params-label:

Listing query params
~~~~~~~~~~~~~~~~~~~~

* *limit*: the number of records requested.
* *next*: the URL for the next page in the pagination.
* *offset*: where in the result set the listing started.
* *previous*: the URL for the previous page in the pagination.
* *total_count*: the total number of records.

.. _objects-response-label:

Listing response objects
~~~~~~~~~~~~~~~~~~~~~~~~

This is a list of the objects returned by the listing. The contents of the
objects depends upon the listing in question. For example:

    .. code-block:: json

        {
            "objects": [{
                "id": "156",
                "name": "Music",
                "resource_uri": "/api/v1/apps/category/156/",
                "slug": "music"
            }, {
                "id": "157",
                "name": "News",
                "resource_uri": "/api/v1/apps/category/157/",
                "slug": "news-weather"
            }, {
                "id": "158",
                "name": "Productivity",
                "resource_uri": "/api/v1/apps/category/158/",
                "slug": "productivity"
            }]
        }

All objects in the database will have at least two fields:

* *id*: the unique id of that object.
* *resource_uri*: the URL of that object for more detailed information.

Cross Origin
============

All APIs are available with `Cross-Origin Resource Sharing`_ unless otherwise
specified.

.. _`MDN`: https://developer.mozilla.org
.. _`Marketplace representative`: marketplace-team@mozilla.org
.. _`django-tastypie`: https://github.com/toastdriven/django-tastypie
.. _`APIs for Add-ons`: https://developer.mozilla.org/en/addons.mozilla.org_%28AMO%29_API_Developers%27_Guide
.. _`example marketplace client`: https://github.com/mozilla/Marketplace.Python
.. _`Cross-Origin Resource Sharing`: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS
