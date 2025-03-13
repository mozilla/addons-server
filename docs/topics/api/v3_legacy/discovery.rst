=========
Discovery
=========

.. warning::

    These v3 APIs are now deprecated and you should switch to a newer version before
    it is removed. See :ref:`the API versions available<api-versions-list>` for details
    of the different API versions available and the deprecation timeline.

-----------------
Discovery Content
-----------------

.. _v3-disco-content:

This endpoint allows you to fetch content for the new Discovery Pane in
Firefox (about:addons).

 .. http:get:: /api/v3/discovery/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <v3-api-overview-translations>`)
    :query string edition: Return content for a specific edition of Firefox.  Currently only ``china`` is supported.
    :>json int count: The number of results for this query.
    :>json array results: The array containing the results for this query.
    :>json string results[].heading: The heading for this item. May contain some HTML tags.
    :>json string|null results[].description: The description for this item, if any. May contain some HTML tags.
    :>json boolean results[].is_recommendation: Always False
    :>json object results[].addon: The :ref:`add-on <v3-addon-detail-object>` for this item. Only a subset of fields are present: ``id``, ``current_version`` (with only the ``compatibility`` and ``files`` fields present), ``guid``, ``icon_url``, ``name``, ``slug``, ``theme_data``, ``type`` and ``url``.


-------------------------
Discovery Recommendations
-------------------------

.. _v3-disco-recommendations:

E.g. a standard discovery pane will display 7 items, 4 extensions and 3 themes.
Up to 4 extensions will be replaced with recommendations; the 3 themes will not
be replaced. The API will still return a total of 7 items.

.. note::
    A standard discovery pane will display 7 items, 4 extensions and 3 themes.

    Specifying an ``edition`` parameter disables recommendations - the ``telemetry-client-id``
    is ignored and standard discovery response returned.


 .. http:get:: /api/v3/discovery/?telemetry-client-id=12345678-90ab-cdef-1234-567890abcdef

    :query string telemetry-client-id: Ignored. Was previously an optional sha256 hash of the telemetry client ID to be passed to the TAAR service to enable recommendations.
    :query string lang: Activates translations (see :ref:`Discovery Content <v3-disco-content>`).
    :query string platform: Ignored.
    :query string branch: Ignored.
    :query string study: Ignnored.
