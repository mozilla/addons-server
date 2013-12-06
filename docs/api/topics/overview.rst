.. _overview:

========
Overview
========

This describes the details of the requests and responses you can
expect from the Firefox Marketplace API.

Requests
========

All requests should be made with the header::

        Content-type: application/json

If you access the URLs in this document in a browser, then prepend
`?format=json` on to the request.

Verbs
~~~~~

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

Versions
~~~~~~~~

This API is versioned and we are currently moving towards version 1 of the API.
The API will be versioned by the URL, so that version 1 APIs will all be at::

    /api/v1/...

If you are not using the most recent version of the API then you will get
a header in the response::

    API-Status: Deprecated

The current policy for how long deprecated APIs will exist has not been
defined, but it would include time for any clients to upgrade before versions
are turned off.

We will also return the version of the API we think you are using::

    API-Version: 1

.. note: Before v1 is released, the API was unversioned at `/api/v1/`, because
    of the small number of clients using that URL, we hope all users are able to
    update to `/api/v1/` quickly so we can remove that unversioned URL.


Modifying Results
~~~~~~~~~~~~~~~~~

In order to return the most relevant results for the client, the API attempts
to detect and filter responses by region and language. Additionally, it is
possible to globally restrict responses by device type and carrier.

The API will report which filters are implemented via the URL-encoded
`API-Filter` header in responses::

    API-Filter: lang=en-US&device=&region=us&carrier=

In some cases, such as that where the API consumer is actually a proxy for the
end user, it may be appropriate to manually set one or more of these parameters.

Carrier
+++++++

Responses may be modified to include results relevent to a specific carrier by
passing the `carrier` querystring parameter. This must be set to a slug
representing an item from the `list of carriers`_.


Region
++++++

Responses may be modified to include results relevent to a specific region by
passing the `region` querystring parameter. This must be set to a slug
representing an item from the `list of regions`_.


Language
++++++++

Responses may be filtered to only include results for a specific language. This
is done by inspecting the value of the `Accept-Language` header on the request.
This value may be overriden via the `lang` querystring parameter. This may be
set to any of the valid `RFC 3060 languages`_.


Device
++++++

Responses may be filtered to only include results relevant for one or more types
of devices.

* `gaia` - return results relevant to `Gaia`_.
* `mobile` - return results relevant to mobile devices.
* `tablet` - return results relevant to tablets.

The `API-Filter` header will represent this as a representation of a list in a
queryset::

    API-Filter: device=mobile&device=gaia

You may override these values with separate querystring values for each device
type::

    gaia=true&mobile=true&tablet=false


Responses
=========

Because the responses can be quite long, rather than show the full result, we
link to examples of the results.  All responses are in JSON. The client must
send either no HTTP `Accept` header, or a value of `application\json`. Any
other value will result in 400 status code.

Data errors
~~~~~~~~~~~

If there is an error in your data, a 400 status code will be returned. There
can be multiple errors per field. Example:

    .. code-block:: json

        {
            "error_message": {
                "manifest": ["This field is required."]
            }
        }

Rate limiting
~~~~~~~~~~~~~

Select API endpoints are rate-limited. When an application exceeds the rate
limit for a given endpoint, the API will return an HTTP 429 response.

Other errors
~~~~~~~~~~~~

The appropriate HTTP status code will be returned, with the error in JSON.

Listings
~~~~~~~~

When the API returns a list of objects, it will generally return a response in
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

.. _overview-translations:

Translations
++++++++++++

Fields that can be translated by users (typically name, description) have a
special behaviour. The default is to return them as an object, with languages
as keys and translations as values:

.. code-block:: json

    "name": {
        "en-US": "Games",
        "fr": "Jeux",
        "kn": "ಆಟಗಳು"
    }

However, for performance sake, if you pass the `lang` parameter to
a `GET` request, then only the most relevant translation (the specified
language or the fallback, depending on whether a translation is available)
will be returned as a string.

.. code-block:: json

    "name": "Games"

This behaviour also applies to `POST`, `PATCH` and `PUT` requests: you can
either submit a object containing several translations, or just a string. If
only a string is supplied, it will only be used to translate the field in the
current language.

Cross Origin
~~~~~~~~~~~~

All APIs are available with `Cross-Origin Resource Sharing`_ unless otherwise
specified.

Timestamps
~~~~~~~~~~

Timestamps use the `%Y-%m-%dT%H:%M:%S` format (`Python's strftime notation`_),
using the `America/Los_Angeles time zone`_.


.. _`Firefox Marketplace`: https://marketplace.firefox.com
.. _`MDN`: https://developer.mozilla.org
.. _`Marketplace representative`: marketplace-team@mozilla.org
.. _`django-tastypie`: https://github.com/toastdriven/django-tastypie
.. _`APIs for Add-ons`: https://developer.mozilla.org/en/addons.mozilla.org_%28AMO%29_API_Developers%27_Guide
.. _`example marketplace client`: https://github.com/mozilla/Marketplace.Python
.. _`Cross-Origin Resource Sharing`: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS
.. _`list of carriers`: https://github.com/mozilla/zamboni/blob/master/mkt/constants/carriers.py
.. _`list of regions`: https://github.com/mozilla/zamboni/blob/master/mkt/constants/regions.py
.. _`RFC 3060 languages`: http://tools.ietf.org/html/rfc3066
.. _`Gaia`: https://developer.mozilla.org/en-US/docs/Mozilla/Firefox_OS/Platform/Gaia
.. _`Python's strftime notation`: http://docs.python.org/2/library/time.html#time.strftime
.. _`America/Los_Angeles time zone`: https://en.wikipedia.org/wiki/America/Los_Angeles
