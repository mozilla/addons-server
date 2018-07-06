=========
Discovery
=========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability.

-----------------
Discovery Content
-----------------

.. _disco-content:

This endpoint allows you to fetch content for the new Discovery Pane in
Firefox (about:addons).

 .. http:get:: /api/v4/discovery/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string edition: Return content for a specific edition of Firefox.  Currently only ``china`` is supported.
    :>json int count: The number of results for this query.
    :>json array results: The array containing the results for this query.
    :>json string results[].heading: The heading for this item. May contain some HTML tags.
    :>json string|null results[].description: The description for this item, if any. May contain some HTML tags.
    :>json boolean results[].is_recommendation: If this item was from the recommendation service, rather than static curated content.
    :>json object results[].addon: The :ref:`add-on <addon-detail-object>` for this item. Only a subset of fields are present: ``id``, ``current_version`` (with only the ``compatibility`` and ``files`` fields present), ``guid``, ``icon_url``, ``name``, ``slug``, ``theme_data``, ``type`` and ``url``.


-------------------------
Discovery Recommendations
-------------------------

.. _disco-recommendations:

If a telemetry client id is passed as a parameter to the discovery pane api
endpoint then static curated content is amended with recommendations from the
`recommendation service <https://github.com/mozilla/taar>`_.  The same number
of results will be returned as a standard discovery response and only extensions
(not themes) are recommeded.  Only valid, publicly available addons are shown.

E.g. a standard discovery pane will display 7 items, 4 extensions and 3 themes.
Up to 4 extensions will be replaced with recommendations; the 3 themes will not
be replaced. The API will still return a total of 7 items.

.. note::
    Specifying an ``edition`` parameter disables recommendations - the ``telemetry-client-id``
    is ignored and standard discovery response returned.


 .. http:get:: /api/v4/discovery/?telemetry-client-id=12345678-90ab-cdef-1234-567890abcdef

    :query string telemetry-client-id: The telemetry client ID to be passed to the TAAR service.
    :query string lang: In addition to activating translations (see :ref:`Discovery Content <disco-content>`), this will be passed as `locale` to TAAR.
    :query string platform: The platform identifier to be passed to TAAR.
    :query string branch: Additional parameter passed along to TAAR.
    :query string study: Additional parameter passed along to TAAR.

-----------------
Editorial Content
-----------------

.. _disco-editorial-content:

This endpoint allows you to fetch all editorial content for Discovery Pane
Recommendations. This is used internally to generate .po files containing the
strings the content team came up with.

 .. http:get:: /api/v4/discovery/editorial/

    :>json array results: The array containing the results for this query. There is no pagination, all results are returned.
    :>json string|null results[].custom_heading: The custom heading for this item, if any.
    :>json string|null results[].custom_description: The custom description for this item, if any.
