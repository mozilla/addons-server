=======
Add-ons
=======

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning.

------
Search
------

.. _addon-search:

This endpoint allows you to search through public add-ons.

.. http:get:: /api/v3/addons/search/

    :param q: The search query.
    :>json count: The number of results for this query.
    :>json next: The URL of the next page of results.
    :>json previous: The URL of the previous page of results.
    :>json results: An array of :ref:`add-ons <addon-detail>`.

------
Detail
------

.. _addon-detail:

This endpoint allows you to fetch a specific add-on by id, slug or guid.

**Not implemented yet**.

.. http:get:: /api/v3/addons/addon/(int:id|string:slug|string:guid)/

    :>json id: The add-on id.
    :>json default_locale: The add-on default locale for translations.
    :>json name: The add-on name.
    :>json last_updated: The date of the last time the add-on was updated by its developer(s).
    :>json slug: The add-on slug.
