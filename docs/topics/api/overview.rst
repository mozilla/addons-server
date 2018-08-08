.. _api-overview:

========
Overview
========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability.

This describes the details of the requests and responses you can expect from
the `addons.mozilla.org <https://addons.mozilla.org/en-US/firefox/>`_ API.

--------
Requests
--------

All requests should be made with the header::

        Content-type: application/json

---------
Responses
---------

~~~~~~~~~~~~
Status Codes
~~~~~~~~~~~~

There are some common API responses that you can expect to receive at times.

.. http:get:: /api/v4/...

    :statuscode 200: Success.
    :statuscode 201: Creation successful.
    :statuscode 202: The request has been accepted for processing.
        This usually means one or more asyncronous tasks is being executed in
        the background so results aren't immediately visible.
    :statuscode 204: Success (no content is returned).
    :statuscode 400: There was a problem with the parameters sent with this
        request.
    :statuscode 401: Authentication is required or failed.
    :statuscode 403: You are not permitted to perform this action.
    :statuscode 404: The requested resource could not be found.
    :statuscode 500: An unknown error occurred.
    :statuscode 503: The site is in maintenance mode at this current time and
        the operation can not be performed.

~~~~~~~~~~~~
Bad Requests
~~~~~~~~~~~~

When returning a ``HTTP 400 Bad Request`` response, the API will try to return
some information about the error(s) in the body of the response, as a JSON
object. The keys of that object indicate the field(s) that caused an error, and
for each, a list of messages will be provided (often only one message will be
present, but sometimes more). If the error is not attached to a specific field
the key ``non_field_errors`` will be used instead.

Example:

     .. code-block:: json

         {
             "username": ["This field is required."],
             "non_field_errors": ["Error not linked to a specific field."]
         }

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unauthorized and Permission Denied
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When returning ``HTTP 401 Unauthorized`` and ``HTTP 403 Permission Denied``
responses, the API will try to return some information about the error in the
body of the response, as a JSON object. A ``detail`` property will contain a
message explaining the error. In addition, in some cases, an optional ``code``
property will be present and will contain a constant corresponding to
specific problems to help clients address the situation programmatically. The
constants are as follows:

    ========================  =========================================================
                       Value  Description
    ========================  =========================================================
        ERROR_INVALID_HEADER  The ``Authorization`` header is invalid.
     ERROR_SIGNATURE_EXPIRED  The signature of the token indicates it has expired.
    ERROR_DECODING_SIGNATURE  The token was impossible to decode and probably invalid.
    ========================  =========================================================


~~~~~~~~~~
Pagination
~~~~~~~~~~

By default, all endpoints returning a list of results are paginated.
The default number of items per page is 25 and clients can use the `page_size`
query parameter to change it to any value between 1 and 50. Exceptions to those
rules are possible but will be noted in the corresponding documentation for
affected endpoints.

The following properties will be available in paginated responses:

* *next*: the URL for the next page in the pagination.
* *previous*: the URL for the previous page in the pagination.
* *page_size*: The number of items per page in the pagination.
* *page_count*: The number of pages available in the pagination. It may be
  lower than `count / page_size` for elasticsearch based paginations that
  go beyond our `max_result_window` configuration.
* *count*: the total number of records.
* *results*: the array containing the results for this page.


.. _api-overview-translations:

~~~~~~~~~~~~~~~~~
Translated Fields
~~~~~~~~~~~~~~~~~

Fields that can be translated by users (typically name, description) have a
special behaviour. They are returned as an object, with languages as keys and
translations as values, and by default all languages are returned:

.. code-block:: json

    {
        "name": {
            "en-US": "Games",
            "fr": "Jeux",
            "kn": "ಆಟಗಳು"
        }
    }

However, for performance, if you pass the ``lang`` parameter to a ``GET``
request, then only the most relevant translation (the specified language or the
fallback, depending on whether a translation is available in the requested
language) will be returned.

.. code-block:: json

    {
        "name": {
            "en-US": "Games"
        }
    }

For ``POST``, ``PATCH`` and ``PUT`` requests you submit an object containing
translations for any languages needing to be updated/saved.  Any language not
in the object is not updated, but is not removed.

For example, if there were existing translations of::

"name": {"en-US": "Games", "fr": "Jeux","kn": "ಆಟಗಳು"}

and the following request was made:

.. code-block:: json

    {
        "name": {
            "en-US": "Fun"
        }
    }

Then the resulting translations would be::

"name": {"en-US": "Fun", "fr": "Jeux","kn": "ಆಟಗಳು"}

To delete a translation, pass ``null`` as the value for that language.
(Note: this behavior is currently buggy/broken - see
https://github.com/mozilla/addons-server/issues/8816 for more details)


.. _api-overview-outgoing:

~~~~~~~~~~~~~~
Outgoing Links
~~~~~~~~~~~~~~

If the ``wrap_outgoing_links`` query parameter is present, any external links
returned for properties such as ``support_url`` or ``homepage`` will be wrapped
through ``outgoing.prod.mozaws.net``. Fields supporting some HTML, such as
add-on ``description``, always do this regardless of whether or not the query
parameter is present.

~~~~~~~~~~~~
Cross Origin
~~~~~~~~~~~~

All APIs are available with `Cross-Origin Resource Sharing`_ unless otherwise
specified.


.. _`Cross-Origin Resource Sharing`: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS

.. _api-stable-v3:

-------------
Stable v3 API
-------------

All documentation here refers to the in-development `v4` APIs, which are
experimental. Any consumer of the APIs that require stablity may consider using
the `v3` API instead, which is frozen.  No new API endpoints will be added to
`v3` and we aim to make no breaking changes.  (That's the aim - we can't
guarantee 100% stability).  The `v3` API will be maintained for as long as Firefox
ESR60 is supported by Mozilla, i.e. at least June 30th 2019.
The downside of using the `v3` API is, of course, no new cool features!

The documentation for `v3` can be accessed at: http://addons-server.readthedocs.io/en/2018.05.17/topics/api/


----------------
v4 API changelog
----------------

* 2018-05-18: renamed /reviews/ endpoint to /ratings/  https://github.com/mozilla/addons-server/issues/6849
* 2018-05-25: renamed ``rating.rating`` property to ``rating.score``  https://github.com/mozilla/addons-server/pull/8332
* 2018-06-05: dropped ``rating.title`` property https://github.com/mozilla/addons-server/issues/8144
* 2018-07-12: added ``type`` property to autocomplete API. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/8803
* 2018-07-19: localised field values are always returned as objects, even if only a single language is requested.
  Setting a localised value with a string is removed too - it must always be an object of one or more translations.
  https://github.com/mozilla/addons-server/issues/8794
* 2018-07-18: added ``previews`` property to discovery API ``addons`` object. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/8863
* 2018-07-20: dropped ``downloads`` property from the collection add-ons results. https://github.com/mozilla/addons-server/issues/8944
* 2018-08-16: added ``is_developer_reply`` property to ratings. This changed was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/8993
