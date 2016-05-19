=========
Discovery
=========

.. note::
    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning.

-----------------
Discovery Content
-----------------

.. _disco-content:

This endpoint allows you to fetch content for the new Discovery Pane in
Firefox (about:addons).

 .. http:get:: /api/v3/discovery/

    :>json int count: The number of results for this query.
    :>json array results: An array of :ref:`discovery items <discovery-item>`.
    :>json string results[].heading: The heading for this item. If present, it contains the following sub-strings, that the client needs to use to format the string as it desires: ``{start_sub_heading}``, ``{end_sub_heading}`` and ``{addon_name}``.
    :>json string|null results[].description: The description for this item, if any. May contain some HTML tags.
    :>json object results[].addon: The :ref:`add-on <addon-detail-object>` for this item. Only a subset of fields are present: ``id``, ``current_version``, ``icon_url``, ``theme_data``, ``type`` and ``url``.
