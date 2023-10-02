.. _v4-api-overview:

========
Overview
========

.. note::

    These v4 APIs are now frozen.
    See :ref:`the API versions available<api-versions-list>` for details of the
    different API versions available.

This describes the details of the requests and responses you can expect from
the `addons.mozilla.org <https://addons.mozilla.org/firefox/>`_ API.

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
    :statuscode 451: The requested resource is not available for legal reasons.
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


.. _v4-api-overview-maintenance:

~~~~~~~~~~~~~~~~~
Maintenance Mode
~~~~~~~~~~~~~~~~~

When returning ``HTTP 503 Service Unavailable`` responses the API may be in
read-only mode. This means that for a short period of time we do not allow any
write requests, this includes ``POST``, ``PATCH``, ``PUT`` and ``DELETE`` requests.

In case we are in read-only mode, the following behavior can be observed:

  * ``GET`` requests behave normally
  * ``POST``, ``PUT``, ``PATCH``, and ``DELETE`` requests return 503 with a json response that contains a localized error message

The response when returning ``HTTP 503 Service Unavailable`` in case of read-only mode looks like this:

.. code-block:: json

    {
        "error": "Some features are temporarily disabled while we perform websi…"
    }

In case we are not in read-only mode everything should be back working as normal.
To check if the site is in read-only mode before submitting a response, the :ref:`site status api<v4-api-site-status>` can be called.

.. _v4-api-overview-pagination:

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


.. _v4-api-overview-translations:

~~~~~~~~~~~~~~~~~
Translated Fields
~~~~~~~~~~~~~~~~~

Fields that can be translated by users (typically name, description) have a
special behaviour. They are returned as an object, by default, with languages as keys and
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


.. _v4-api-overview-translations-v3:

^^^^^^^^^^^^^^^^^^^^
Default API behavior
^^^^^^^^^^^^^^^^^^^^

In API version 3 or 4 the response, if the ``lang`` parameter is passed, is a single string.

.. code-block:: json

    {
        "name": "Games"
    }

This behaviour also applies to ``POST``, ``PATCH`` and ``PUT`` requests: you
can either submit an object containing several translations, or just a string.
If only a string is supplied, it will only be used to translate the field in
the current language.


.. _v4-api-overview-outgoing:

~~~~~~~~~~~~~~
Outgoing Links
~~~~~~~~~~~~~~

How outgoing links are treated has changed in v5 API.

^^^^^^^^^^^^^^^^^^^^^^^^^^
Default v3/v4 API behavior
^^^^^^^^^^^^^^^^^^^^^^^^^^

If the ``wrap_outgoing_links`` query parameter is present, any external links
returned for properties such as ``support_url`` or ``homepage`` will be wrapped
through ``outgoing.prod.mozaws.net``. Fields supporting some HTML, such as
add-on ``description`` or ``summary``, always do this regardless of whether or
not the query parameter is present.


^^^^^^^^^^^^^^^
v5 API behavior
^^^^^^^^^^^^^^^

All fields that can have external links that would be presented to the user,
such as ``support_url`` or ``homepage``, are returned as a object both containing the
original url (``url``), and wrapped through ``outgoing.prod.mozaws.net`` (``outgoing``).

.. code-block:: json

    {
        "contributions": {
            "url": "https://paypal.me/xxx",
            "outgoing": "https://outgoing.prod.mozaws.net/123456"
        }
    }

Note, if the field is also a translated field then the ``url`` and ``outgoing``
values could be an object rather than a string
(See `translated fields <v4-api-overview-translations>` for translated field representations).

Fields supporting some HTML, such as add-on ``description`` or ``summary``,
always wrap any links directly inside the content (the original url is not available).


~~~~~~~~~~~~
Cross Origin
~~~~~~~~~~~~

All APIs are available with `Cross-Origin Resource Sharing`_ unless otherwise
specified.


.. _`Cross-Origin Resource Sharing`: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS


-----------
Site Status
-----------

.. _v4-api-site-status:

This special endpoint returns if the site is in read only mode, and if there is a site notice currently in effect.
See :ref:`maintenance mode <v4-api-overview-maintenance>` for more details of when the site is read only and how requests are affected.


.. http:get:: /api/v4/site/

    .. _v4-site-status-object:

    :>json boolean read_only: Whether the site in read-only mode.
    :>json string|null notice: A site-wide notice about any current known difficulties or restrictions.  If this API is being consumed by a tool/frontend it should be displayed to the user.


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
* 2018-09-13: added ``name`` and ``icon_url`` properties to the ``addon`` object in ratings. This changed was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/9357
* 2018-09-27: backed out "localised field values are always returned as objects" change from 2018-07-19 from `v4` API.  This is intended to be temporary change while addons-frontend upgrades.
  On addons-dev and addons stage environments the previous behavior is available as `api/v4dev`. The `v4dev` api is not available on AMO production server.
  https://github.com/mozilla/addons-server/issues/9467
* 2018-10-04: added ``is_strict_compatibility_enabled`` to discovery API ``addons.current_version`` object. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/9520
* 2018-10-04: added ``is_deleted`` to the ratings API. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/9371
* 2018-10-04: added ``exclude_ratings`` parameter to ratings API. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/9424
* 2018-10-11: removed ``locale_disambiguation`` from the Language Tools API.
* 2018-10-11: added ``created`` to the addons API.
* 2018-10-18: added ``_score`` to the addons search API.
* 2018-10-25: changed ``author`` parameter on addons search API to accept user ids as well as usernames. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/8901
* 2018-10-25: added ``fxa_edit_email_url`` parameter on accounts API to return the full URL for editing the user's email on FxA. https://github.com/mozilla/addons-server/issues/8674
* 2018-10-31: added ``id`` to discovery API ``addons.current_version`` object. This change was also backported to the `v3` API. https://github.com/mozilla/addons-server/issues/9855
* 2018-11-15: added ``is_custom`` to the license object in version detail output in the addons API.
* 2018-11-22: added ``flags`` to the rating object in the ratings API when ``show_flags_for`` parameter supplied.
* 2018-11-22: added ``score`` parameter to the ratings API list endpoint.
* 2019-01-10: added ``release_notes`` and ``license`` (except ``license.text``) to search API results ``current_version`` objects.
* 2019-01-11: added new /reviewers/browse/ endpoint. https://github.com/mozilla/addons-server/issues/10322
* 2019-01-16: removed /api/{v3,v4,v5}/github api entirely. They have been marked as experimental. https://github.com/mozilla/addons-server/issues/10411
* 2019-02-21: added new /api/v4/reviewers/addon/(addon_id)/versions/ endpoint. https://github.com/mozilla/addons-server/issues/10432
* 2019-03-14: added new /reviewers/compare/ endpoint. https://github.com/mozilla/addons-server/issues/10323
* 2019-04-11: removed ``id``, ``username`` and ``url`` from the ``user`` object in the activity review notes APIs. https://github.com/mozilla/addons-server/issues/11002
* 2019-04-18: added new optional parameters to abuse report endpoint
* 2019-05-09: added ``is_recommended`` to addons API. https://github.com/mozilla/addons-server/issues/11278
* 2019-05-16: added /reviewers/canned-responses/ endpoint. https://github.com/mozilla/addons-server/issues/11276
* 2019-05-23: added ``is_recommended`` to addons autocomplete API also. https://github.com/mozilla/addons-server/issues/11439
* 2019-05-23: changed the addons search API default sort when no query string is passed - now ``sort=recommended,downloads``.
  Also made ``recommended`` sort available generally to the addons search API.  https://github.com/mozilla/addons-server/issues/11432
* 2019-06-27: removed ``sort`` parameter from addon autocomplete API.  https://github.com/mozilla/addons-server/issues/11664
* 2019-07-18: completely changed the 2019-05-16 added draft-comment related APIs. See `#11380`_, `#11379`_, `#11378`_ and `#11374`_
* 2019-07-25: added /hero/ endpoint to expose recommended addons and other content to frontend to allow customizable promos https://github.com/mozilla/addons-server/issues/11842.
* 2019-08-01: added alias ``edition=MozillaOnline`` for ``edition=china`` in /discovery/ endpoint.
* 2019-08-08: add support for externally hosted addons to /hero/ endpoints.  https://github.com/mozilla/addons-server/issues/11882
* 2019-08-08: removed ``heading_text`` property from discovery api. https://github.com/mozilla/addons-server/issues/11817
* 2019-08-08: add secondary shelf to /hero/ endpoint. https://github.com/mozilla/addons-server/issues/11779
* 2019-08-15: dropped support for LWT specific statuses.
* 2019-08-15: added promo modules to secondary hero shelves. https://github.com/mozilla/addons-server/issues/11780
* 2019-08-15: removed /addons/compat-override/ from v4 and above.  Still exists in /v3/ but will always return an empty response. https://github.com/mozilla/addons-server/issues/12063
* 2019-08-22: added ``canned_response`` property to draft comment api. https://github.com/mozilla/addons-server/issues/11807
* 2019-09-19: added /site/ endpoint to expose read-only mode and any site notice.  Also added the same response to the /accounts/account/ non-public response as a convenience for logged in users. https://github.com/mozilla/addons-server/issues/11493)
* 2019-10-17: moved /authenticate endpoint from api/v4/accounts/authenticate to version-less api/auth/authenticate-callback https://github.com/mozilla/addons-server/issues/10487
* 2019-11-14: removed ``is_source_public`` property from addons API https://github.com/mozilla/addons-server/issues/12514
* 2019-12-05: removed /addons/featured endpoint from v4+ and featured support from other addon api endpoints.  https://github.com/mozilla/addons-server/issues/12937
* 2020-01-23: added /scanner/results (internal API endpoint).
* 2020-02-06: added /reviewers/addon/(int:addon_id)/allow_resubmission/ and /reviewers/addon/(int:addon_id)/deny_resubmission/. https://github.com/mozilla/addons-server/issues/13409
* 2020-02-20: added ``addon_install_source_url`` to abuse report endpoint
* 2020-03-19: added /blocklist/block endpoint to expose add-on blocks https://github.com/mozilla/addons-server/issues/13706.
* 2020-03-26: added ``addon_name`` to blocklist/block api https://github.com/mozilla/addons-server/issues/13757
* 2020-08-13: added ``applications`` internal API to create new application versions https://github.com/mozilla/addons-server/issues/14649
* 2020-09-03: added ``promoted`` filter to addons search api https://github.com/mozilla/addons-server/issues/15272.
* 2020-09-17: dropped ``is_recommended`` from addons api - use ``promoted`` propety instead.  https://github.com/mozilla/addons-server/issues/15271
* 2020-09-17: dropped ``recommended=true`` filter from addons api - use ``promoted=recommended`` filter instead.  https://github.com/mozilla/addons-server/issues/15467
* 2020-09-17: added ``?promoted=badged`` search filter to addons api. https://github.com/mozilla/addons-server/issues/15468
* 2020-10-08: added channel-specific reviewer submission subscriptions endpoints. https://github.com/mozilla/addons-server/issues/15605
* 2020-10-15: moved hero shelves documentation to /shelves from /hero.
* 2020-10-15: added /shelves/sponsored/ endpoint https://github.com/mozilla/addons-server/issues/15617
* 2020-10-15: added /shelves/sponsored/impression and /shelves/sponsored/click endpoints https://github.com/mozilla/addons-server/issues/15618 and https://github.com/mozilla/addons-server/issues/15619
* 2020-10-22: added ``promoted`` to primary hero shelf addon object. https://github.com/mozilla/addons-server/issues/15741
* 2020-10-22: added /shelves/sponsored/event endpoint for conversions, and to replace click endpoint https://github.com/mozilla/addons-server/issues/15718
* 2020-11-05: dropped heading and description from discovery API https://github.com/mozilla/addons-server/issues/11272
* 2020-11-05: added endpoint to receive Stripe events. https://github.com/mozilla/addons-server/issues/15879
* 2021-01-28: removed the /shelves/ endpoints from /v4/.  They are only useful internally within AMO and are still under rapid development making them unsuitable for a frozen API.

.. _`#11380`: https://github.com/mozilla/addons-server/issues/11380/
.. _`#11379`: https://github.com/mozilla/addons-server/issues/11379/
.. _`#11378`: https://github.com/mozilla/addons-server/issues/11378/
.. _`#11374`: https://github.com/mozilla/addons-server/issues/11374/
