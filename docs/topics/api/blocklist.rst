=========
Blocklist
=========

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.


------
Blocks
------

.. _blocklist-block:

This endpoint returns an add-on Block from the blocklist, specified by guid or id.


.. http:get:: /api/v5/blocklist/block/(int:block_id|string:guid)

    :query string lang: Activate translations in the specific language for that query. (See :ref:`Translated Fields <api-overview-translations>`)
    :>json int id: The id for the block.
    :>json string created: The date the block was created.
    :>json string modified: The date the block was last updated.
    :>json object|null addon_name: The add-on name, if we have details of an add-on matching that guid (See :ref:`translated fields <api-overview-translations>`).
    :>json string guid: The guid of the add-on being blocked.
    :>json string|null reason: Why the add-on needed to be blocked.
    :>json object|null url: A url to the report/request that detailed why the add-on should potentially be blocked.  Typically a bug report on bugzilla.mozilla.org.  (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json string blocked[]: The versions of this add-on that are (hard) blocked.
    :>json string soft_blocked[]: The versions of this add-on that are soft blocked (can be optionally re-enabled by existing users).
    :>json boolean is_all_versions: Are all versions of this add-on blocked. If ``False``, some versions are not blocked.
