=========
Discovery
=========

.. note::

    These v4 APIs are now frozen.
    See :ref:`the API versions available<api-versions-list>` for details of the
    different API versions available.

-----------------
Discovery Content
-----------------

.. _v4-disco-content:

This endpoint allows you to fetch content for the new Discovery Pane in
Firefox (about:addons).

.. _v4-disco-recommendations:

.. note::

    If a telemetry client id is passed as a parameter to the discovery pane api
    endpoint then static curated content is amended with recommendations from the
    `recommendation service <https://github.com/mozilla/taar>`_.  The same number
    of results will be returned as a standard discovery response and only extensions
    (not themes) are recommeded.  Only valid, publicly available addons are shown.

    E.g. a standard discovery pane will display 7 items, 4 extensions and 3 themes.
    Up to 4 extensions will be replaced with recommendations; the 3 themes will not
    be replaced. The API will still return a total of 7 items.

.. http:get:: /api/v4/discovery/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v4-api-overview-translations>`)
    :query string edition: Optionally return content for a specific edition of Firefox.  Currently only ``china`` (and the alias ``MozillaOnline``)  is supported.
    :query string telemetry-client-id: Optional sha256 hash of the telemetry client ID to be passed to the TAAR service to enable recommendations. Must be the hex value of a sha256 hash, otherwise it will be ignored.
    :>json int count: The number of results for this query.
    :>json array results: The array containing the results for this query.
    :>json string|null results[].description_text: The description for this item, if any. Text-only, content might slightly differ from ``description`` because of that.
    :>json boolean results[].is_recommendation: If this item was from the recommendation service, rather than static curated content.
    :>json object results[].addon: The :ref:`add-on <v4-addon-detail-object>` for this item. Only a subset of fields are present: ``id``, ``authors``, ``average_daily_users``, ``current_version`` (with only the ``id``, ``compatibility``, ``is_strict_compatibility_enabled`` and ``files`` fields present), ``guid``, ``icon_url``, ``name``, ``ratings``, ``previews``, ``slug``, ``theme_data``, ``type`` and ``url``.


-----------------
Editorial Content
-----------------

.. _v4-disco-editorial-content:

This endpoint allows you to fetch all editorial content for Discovery Pane
Recommendations. This is used internally to generate .po files containing the
strings defined by the content team.  It is also used by TAAR service to obtain a list
of appropriate add-ons to recommended.

 .. http:get:: /api/v4/discovery/editorial/

    :query boolean recommended: Filter to only add-ons recommended by Mozilla.  Only ``recommended=true`` is supported.
    :>json array results: The array containing the results for this query. There is no pagination, all results are returned.
    :>json object results[].addon: A :ref:`add-on <v4-addon-detail-object>` object for this item, but only containing one field: ``guid``.
    :>json string|null results[].custom_description: The custom description for this item, if any.
