=========
Blocklist
=========

.. note::

    These v4 APIs are now frozen.
    See :ref:`the API versions available<api-versions-list>` for details of the
    different API versions available.


------
Blocks
------

.. _v4-blocklist-block:

This endpoint returns an add-on Block from the blocklist, specified by guid or id.


.. http:get:: /api/v4/blocklist/block/(int:block_id|string:guid)

    :query string lang: Activate translations in the specific language for that query. (See :ref:`Translated Fields <v4-api-overview-translations>`)
    :query string wrap_outgoing_links: (v3/v4 only) If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <v4-api-overview-outgoing>`)
    :>json int id: The id for the block.
    :>json string created: The date the block was created.
    :>json string modified: The date the block was last updated.
    :>json string|object|null addon_name: The add-on name, if we have details of an add-on matching that guid (See :ref:`translated fields <v4-api-overview-translations>`).
    :>json string guid: The guid of the add-on being blocked.
    :>json string min_version: The minimum version of the add-on that will be blocked.  "0" is the lowest version, meaning all versions up to max_version will be blocked.  ("0" - "*" would be all versions).
    :>json string max_version: The maximum version of the add-on that will be blocked.  "*" is the highest version, meaning all versions from min_version will be blocked.  ("0" - "*" would be all versions).
    :>json string|null reason: Why the add-on needed to be blocked.
    :>json string|object|null url: A url to the report/request that detailed why the add-on should potentially be blocked.  Typically a bug report on bugzilla.mozilla.org.  (See :ref:`Outgoing Links <v4-api-overview-outgoing>`)
