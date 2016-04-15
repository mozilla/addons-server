========
Internal
========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

-------------
Add-on Search
-------------

.. _addon-search:

This endpoint allows you to search through all add-ons. It's similar to the
:ref:`regular add-on search API <addon-search>`, but is not limited to public
add-ons, and can return disabled, unreviewer, unlisted or even deleted add-ons.

.. note::
    Requires authentication and `AdminTools::View` or `ReviewerAdminTools::View`
    permissions.

.. http:get:: /api/v3/internal/addons/search/

    :param string q: The search query.
    :param string sort: The sort parameter. See :ref:`add-on search sorting parameters <addon-search-sort>`.
    :>json int count: The number of results for this query.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`add-ons <addon-detail-object>`.
