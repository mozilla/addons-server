.. _api-overview:

========
Overview
========

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for details
    if you need stability.

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

.. http:get:: /api/v5/...

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

    ============================  =====================================================
                           Value  Description
    ============================  =====================================================
            ERROR_INVALID_HEADER  The ``Authorization`` header is invalid.
         ERROR_SIGNATURE_EXPIRED  The signature of the token indicates it has expired.
        ERROR_DECODING_SIGNATURE  The token was impossible to decode and probably
                                  invalid.
    ERROR_AUTHENTICATION_EXPIRED  The payload references an invalid session hash,
                                  probably because the session has expired.
    ============================  =====================================================


.. _api-overview-maintenance:

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
To check if the site is in read-only mode before submitting a response, the :ref:`site status api<api-site-status>` can be called.

.. _api-overview-pagination:

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
language) will be returned, and the other translations are omitted from the response.
The response is always an object.

For example, for a request ``?lang=en-US``:

.. code-block:: json

    {
        "name": {
            "en-US": "Games"
        }
    }

If, however, a request is made with a ``lang`` parameter for a language that doesn't exist for that object
then a fallback translation is returned, the requested language is included with a value of ``null``, and the language of the fallback is indicated.
For example, for a request ``?lang=de``:

.. code-block:: json

    {
        "name": {
            "en-US": "Games",
            "de": null,
            "_default": "en-US"
        }
    }


.. warning::
    ``lang`` must only contains alphanumeric characters (plus ``-`` and ``_``).


For ``POST``, ``PATCH`` and ``PUT`` requests you submit an object containing
translations for any languages needing to be updated/saved.  Any language not
in the object is not updated, but is not removed.

For example, if there were existing translations of::

"name": {"en-US": "Games", "fr": "Jeux","kn": "ಆಟಗಳು"}

and the following data was submitted in a request:

.. code-block:: json

    {
        "name": {
            "en-US": "Fun"
        }
    }

Then the resulting translations would be::

"name": {"en-US": "Fun", "fr": "Jeux","kn": "ಆಟಗಳು"}

To delete a translation, pass ``null`` as the value for that language.


.. _api-overview-outgoing:

~~~~~~~~~~~~~~
Outgoing Links
~~~~~~~~~~~~~~

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
(See :ref:`translated fields <api-overview-translations>` for translated field representations).

Fields supporting some HTML, such as add-on ``description`` or ``summary``,
always wrap any links directly inside the content (the original url is not available).


~~~~~~~~~~~~
Cross Origin
~~~~~~~~~~~~

All APIs are available with `Cross-Origin Resource Sharing`_ unless otherwise
specified.


.. _`Cross-Origin Resource Sharing`: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS


.. _api-versions-list:


-----------
Site Status
-----------

.. _`api-site-status`:

This special endpoint returns if the site is in read only mode, and if there is a site notice currently in effect.
See :ref:`maintenance mode <api-overview-maintenance>` for more details of when the site is read only and how requests are affected.


.. http:get:: /api/v5/site/

    .. _site-status-object:

    :>json boolean read_only: Whether the site in read-only mode.
    :>json string|null notice: A site-wide notice about any current known difficulties or restrictions.  If this API is being consumed by a tool/frontend it should be displayed to the user.


------------
API Versions
------------

~~~~~~~~~~~~~~
Default v5 API
~~~~~~~~~~~~~~

All documentation here, unless otherwise specified, refers to the default `v5` APIs,
which are considered stable.
The request and responses are *NOT* frozen though, and can change at any time,
depending on the requirements of addons-frontend (the primary consumer).


~~~~~~~~~~~~~
Frozen v4 API
~~~~~~~~~~~~~

Any consumer of the APIs that requires more stablity may consider using
the `v4` API instead, which is frozen.  No new API endpoints (so no new features)
will be added to `v4` and we aim to make no breaking changes.
Despite the aim, we can't guarantee 100% stability.

The documentation for `v4` can be accessed at: :ref:`v4-api-index`


~~~~~~~~~~~~~~~~~
Deprecated v3 API
~~~~~~~~~~~~~~~~~

The `v3` is now deprecated.  If you are using this API you should switch to `v4`,
which is now frozen.
The `v3` API will be maintained and available until at least 31st December 2021.

The documentation for `v3` can be accessed at: :ref:`v3-api-index`


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
* 2021-01-14: as addons-frontend now uses /v5/, v5 becomes the stable default; v4 becomes frozen; v3 is deprecated
* 2021-02-12: added ``versions_url`` to addon detail endpoint. https://github.com/mozilla/addons-server/issues/16534
* 2021-02-25: ``platform`` filtering was removed from add-on search and autocomplete endpoints. https://github.com/mozilla/addons-server/issues/16463

----------------
v5 API changelog
----------------
These are `v5` specific changes - `v4` changes apply also.

* 2018-09-27: created the `v4dev` API.  The `v4dev` api is not available on AMO production server.
  See :ref:`translations<api-overview-translations>` for details on the change to responses containing localisations.
  https://github.com/mozilla/addons-server/issues/9467
* 2019-05-09: renamed the experimental `v4dev` api to `v5` and made the `v5` API generally available (on AMO production also)
* 2020-12-19: changed the structure of the translated fields in a response when a single language is requested but it's missing.
  The requested locale is returned as ``none``, with the default_locale code under the ``_default`` key.
  See :ref:`v5 API translation behavior<api-overview-translations>` for specification and examples.
  https://github.com/mozilla/addons-server/issues/16069
* 2021-01-07: changed API behavior with all fields that could be affected by ``wrap_outgoing_links``.
  Now the url is an object containing both the original url and the wrapped url.  See :ref:`Outgoing Links <api-overview-outgoing>`.
* 2021-01-21: in language-tools api, made ``application`` parameter only mandatory when ``appversion`` parameter is also present, and ignored otherwise.  https://github.com/mozilla/addons-server/issues/12315
* 2021-01-28: dropped the pagination fields from the shelves api (it's still an object with a ``results`` property though). https://github.com/mozilla/addons-server/issues/16342
* 2021-01-28: made ``description_text`` in discovery endpoint a translated field in the response. (It was always localized, we just didn't return it as such). https://github.com/mozilla/addons-server/issues/8712
* 2021-02-04: dropped /shelves/sponsored endpoint https://github.com/mozilla/addons-server/issues/16390
* 2021-02-11: removed Stripe webhook endpoint https://github.com/mozilla/addons-server/issues/16391
* 2021-02-11: added ``show_grouped_ratings`` to addon detail endpoint. https://github.com/mozilla/addons-server/issues/16459
* 2021-02-18: made ``description``, ``headline``, and ``cta.text`` in shelves/hero endpoint translated fields in the response. (They were always localized, we just didn't return them as such). https://github.com/mozilla/addons-server/issues/16515
* 2021-02-18: added ``versions_url`` to addon detail endpoint. https://github.com/mozilla/addons-server/issues/16534
* 2021-02-25: made ``headline`` and ``footer_text`` in shelves endpoint translated fields. Also added shelves/editorial endpoint for the localization process. https://github.com/mozilla/addons-server/issues/16514
* 2021-02-25: ``platform`` filtering was removed from add-on search and autocomplete endpoints. https://github.com/mozilla/addons-server/issues/16463
* 2021-03-04: replaced ``footer_pathname`` and ``footer_text`` with ``footer`` object in shelves api response.  https://github.com/mozilla/addons-server/issues/16575
* 2021-03-18: removed ``platform`` from file objects (it was always ``all``) in all endpoints. https://github.com/mozilla/addons-server/issues/16466
* 2021-05-20: removed ``text`` from license objects in versions list endpoint. https://github.com/mozilla/addons-server/issues/17163
* 2021-07-22: added ``random-tag`` to the possible values of ``endpoint`` in the shelves endpoint. https://github.com/mozilla/addons-server/issues/17482
* 2021-07-29: updated docs shelves footer url to be non-optional. https://github.com/mozilla/addons-server/issues/17544
* 2021-08-05: added ``ratings`` and ``users`` query parameters to addon search api. https://github.com/mozilla/addons-server/issues/17497
* 2021-08-05: removed ``criteria`` from shelves endpoint. https://github.com/mozilla/addons-server/issues/17498
* 2021-08-12: removed ``is_restart_required`` from addons endpoints. https://github.com/mozilla/addons-server/issues/17390
* 2021-09-23: flattened ``files`` in version detail from an array to a single ``file``. https://github.com/mozilla/addons-server/issues/17839
* 2021-09-30: removed ``is_webextension`` from file objects (all addons have been webextensions for a while now) in all endpoints. https://github.com/mozilla/addons-server/issues/17658
* 2021-11-18: added docs for the under-development addon submission & edit apis.
* 2021-11-25: added ``custom_license`` to version create/update endpoints to allow non-predefined licenses to be created and updated. https://github.com/mozilla/addons-server/issues/18034
* 2021-12-09: enabled setting ``tags`` via addon submission and edit apis. https://github.com/mozilla/addons-server/issues/18268
* 2021-12-09: changed ``license`` in version create/update endpoints to accept a license slug rather than numeric ID, and documented supported licenses. https://github.com/mozilla/addons-server/issues/18361
* 2022-01-27: added ``ERROR_AUTHENTICATION_EXPIRED`` error code for authentication failures. https://github.com/mozilla/addons-server/issues/18669
* 2022-02-03: added ``source`` to version detail responses, for developer's own add-ons.  ``source`` can also be set via version create/update endpoints. https://github.com/mozilla/addons-server/issues/9913
* 2022-02-10: added session id auth, for internal api authentication, replacing the existing internal auth based on tokens. https://github.com/mozilla/addons-server/issues/18743
* 2022-03-17: added ``contributions_url`` to be set or changed via addon create/update endpoints. https://github.com/mozilla/addons-server/issues/18267
* 2022-03-24: added ``icon`` to be set or changed via addon update endpoints. https://github.com/mozilla/addons-server/issues/18232
* 2022-04-14: added a ``previews`` endpoint under /addon/ that can be used to create, update, and delete add-on previews for non-themes. https://github.com/mozilla/addons-server/issues/18236
* 2022-04-28: added the ability to delete add-ons via addon detail api endpoint. https://github.com/mozilla/addons-server/issues/19072
* 2022-05-05: added the ability to list and edit add-on authors. https://github.com/mozilla/addons-server/issues/18231
* 2022-05-05: added the ability to delete add-on authors. https://github.com/mozilla/addons-server/issues/19163
* 2022-05-12: added the ability to add new add-on authors, as pending authors. https://github.com/mozilla/addons-server/issues/19164
* 2022-06-02: enabled setting ``default_locale`` via addon submission and edit endpoints. https://github.com/mozilla/addons-server/issues/18235
* 2022-06-16: added the ability to "PUT" an add-on upload to either create or update an add-on. https://github.com/mozilla/addons-server/issues/15353
* 2022-08-25: added ``approval_notes`` for version create or edit, and exposed via the version detail response for authorized developers of the add-on and reviewers. https://github.com/mozilla/addons-server/issues/19554
* 2023-01-05: added ``applications/<application>/`` API endpoint to list all valid appversions for a given application. https://github.com/mozilla/addons-server/issues/20066
* 2023-01-12: added the ability to delete add-on versions. https://github.com/mozilla/addons-server/issues/19784
* 2023-02-23: removed the /reviewers/canned-responses/ endpoint. https://github.com/mozilla/addons-server/issues/20354
* 2023-02-23: removed ``canned-response`` from the /draft_comments/ endpoint. https://github.com/mozilla/addons-server/issues/20353
* 2023-03-02: added specific HTTP 409 status code for add-on/version submissions that already exist
* 2023-03-02: added support for calling the version detail endpoint using a version number instead of an ``id``.
* 2023-03-09: added ``is_disabled`` to version detail and update endpoints, for authenticated developers and reviewers. https://github.com/mozilla/addons-server/issues/20142
* 2023-03-08: restricted ``lang`` parameter to only alphanumeric, ``_``, ``-``. https://github.com/mozilla/addons-server/issues/20452
* 2023-03-09: added ``host_permissions`` to the response of the version detail endpoint. https://github.com/mozilla/addons-server/issues/20418
* 2023-04-13: removed signing api from api/v5+ in favor of addon submission api. https://github.com/mozilla/addons-server/issues/20560
* 2023-06-01: renamed add-ons search endpoint sort by ratings parameter to ``sort=ratings``, ``sort=rating`` is still supported for backwards-compatibility. https://github.com/mozilla/addons-server/issues/20763
* 2023-06-06: added the /addons/browser-mappings/ endpoint. https://github.com/mozilla/addons-server/issues/20798
* 2023-06-22: added ``versions`` to blocklist block endpoint. https://github.com/mozilla/addons-server/issues/20748
* 2023-07-06: added ``is_all_versions`` to blocklist block endpoint. https://github.com/mozilla/addons-server/issues/20857
* 2023-10-12: added ``reporter_name`` and ``reporter_email`` as two optional alternatives to an authenticated reporter in the abuse api. https://github.com/mozilla/addons-server/issues/21268
* 2023-10-26: added ``location`` to abuse api. https://github.com/mozilla/addons-server/issues/21330
* 2023-11-02: removed ``application`` from categories endpoint, flattened ``categories`` in addon detail/search endpoint. https://github.com/mozilla/addons-server/issues/5989
* 2023-11-09: removed reviewers /enable and /disable endpoints. https://github.com/mozilla/addons-server/issues/21356
* 2023-12-07: added ``lang`` parameter to all /abuse/report/ endpoints. https://github.com/mozilla/addons-server/issues/21529
* 2024-06-20: added ``illegal_category`` parameter to all /abuse/report/ endpoints. https://github.com/mozilla/addons/issues/14870
* 2024-06-20: added ``illegal_subcategory`` parameter to all /abuse/report/ endpoints. https://github.com/mozilla/addons/issues/14875

.. _`#11380`: https://github.com/mozilla/addons-server/issues/11380/
.. _`#11379`: https://github.com/mozilla/addons-server/issues/11379/
.. _`#11378`: https://github.com/mozilla/addons-server/issues/11378/
.. _`#11374`: https://github.com/mozilla/addons-server/issues/11374/
