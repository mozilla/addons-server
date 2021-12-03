====
Tags
====

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.

--------
Tag List
--------

.. _tag-list:

Add-ons can be assigned tags, which have simple (unlocalized) strings as names.
The endpoint returns a list of all current tags names. This endpoint is not paginated.

.. http:get:: /api/v5/addons/tags/

    :>json string[]: An array of tag names.
