.. _api-overview:

========
Overview
========

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

.. http:get:: /api/v3/...

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


~~~~~~~~~~
Pagination
~~~~~~~~~~

Unless specified, endpoints returning a list of results will be paginated. The
following properties will be available in the responses of those endpoints:

* *next*: the URL for the next page in the pagination.
* *previous*: the URL for the previous page in the pagination.
* *count*: the total number of records.
* *results*: the array containing the results for this page.


.. _api-overview-translations:

~~~~~~~~~~~~~~~~~
Translated fields
~~~~~~~~~~~~~~~~~

Fields that can be translated by users (typically name, description) have a
special behaviour. The default is to return them as an object, with languages
as keys and translations as values:

.. code-block:: json

    {
        "name": {
            "en-US": "Games",
            "fr": "Jeux",
            "kn": "ಆಟಗಳು"
        }
    }

However, for performance, if you pass the `lang` parameter to a `GET` request,
then only the most relevant translation (the specified language or the
fallback, depending on whether a translation is available in the requested
language) will be returned as a string.

.. code-block:: json

    {
        "name": "Games"
    }

This behaviour also applies to `POST`, `PATCH` and `PUT` requests: you can
either submit an object containing several translations, or just a string. If
only a string is supplied, it will only be used to translate the field in the
current language.

~~~~~~~~~~~~
Cross Origin
~~~~~~~~~~~~

All APIs are available with `Cross-Origin Resource Sharing`_ unless otherwise
specified.


.. _`Cross-Origin Resource Sharing`: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS
