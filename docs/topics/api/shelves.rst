=======
Shelves
=======

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.


---------------------
Combined Hero Shelves
---------------------

.. _hero-shelves:

This convienence endpoint serves a single, randomly selected, primary hero shelf,
and a single, randomly selected secondary hero shelf.


.. http:get:: /api/v4/hero/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query string wrap_outgoing_links: If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json object primary: A :ref:`primary hero shelf <primary-hero-shelf>`.
    :>json object secondary: A :ref:`secondary hero shelf <secondary-hero-shelf>`.


--------------------
Primary Hero Shelves
--------------------

.. _primary-hero-shelf:

This endpoint returns all enabled primary hero shelves.  As there will only ever be a
small number of shelves this endpoint is not paginated.


.. http:get:: /api/v4/hero/primary/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query boolean all: return all shelves - both enabled and disabled.  To be used internally to generate .po files containing the strings defined by the content team.
    :query string raw: If this parameter is present, don't localise description or fall-back to addon metadata.  To be used internally to generate .po files containing the strings defined by the content team.
    :query string wrap_outgoing_links: If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json array results: The array containing the results for this query.
    :>json object results[].gradient: The background colors used for the gradient.
    :>json string results[].gradient.start: The starting color name for gradient - typically top or left. The name is from the `photon color variables <https://github.com/FirefoxUX/photon-colors/blob/master/photon-colors.scss>`_.
    :>json string results[].gradient.end: The ending color name for gradient - typically bottom or right. The name is from the `photon color variables <https://github.com/FirefoxUX/photon-colors/blob/master/photon-colors.scss>`_.
    :>json string|null results[].featured_image: The image used to illustrate the item, if set.
    :>json string|null results[].description: The description for this item, if any.
    :>json object results[].addon: The :ref:`add-on <addon-detail-object>` for this item if the addon is hosted on AMO. Either this field or ``external`` will be present.  Only a subset of fields are present: ``id``, ``authors``, ``average_daily_users``, ``current_version`` (with only the ``id``, ``compatibility``, ``is_strict_compatibility_enabled`` and ``files`` fields present), ``guid``, ``icon_url``, ``name``, ``ratings``, ``previews``, ``promoted``, ``slug``, ``theme_data``, ``type``, and ``url``.
    :>json object results[].external: The :ref:`add-on <addon-detail-object>` for this item if the addon is externally hosted. Either this field or ``addon`` will be present.  Only a subset of fields are present: ``id``, ``guid``, ``homepage``, ``name`` and ``type``.


----------------------
Secondary Hero Shelves
----------------------

.. _secondary-hero-shelf:

This endpoint returns all enabled secondary hero shelves.  As there will only ever be a
small number of shelves - and likely only one - this endpoint is not paginated.


.. http:get:: /api/v4/hero/secondary/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query boolean all: return all shelves - both enabled and disabled.  To be used internally to generate .po files containing the strings defined by the content team.
    :query string wrap_outgoing_links: If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json array results: The array containing the results for this query.
    :>json string results[].headline: The headline for this item.
    :>json string results[].description: The description for this item.
    :>json object|null results[].cta: The optional call to action link and text to be displayed with the item.
    :>json string results[].cta.url: The url the call to action would link to.
    :>json string results[].cta.text: The call to action text.
    :>json array results[].modules: The modules for this shelf.  Should always be 3.
    :>json string results[].modules[].icon: The icon used to illustrate the item.
    :>json string results[].modules[].description: The description for this item.
    :>json object|null results[].modules[].cta: The optional call to action link and text to be displayed with the item.
    :>json string results[].modules[].cta.url: The url the call to action would link to.
    :>json string results[].modules[].cta.text: The call to action text.


----------------
Homepage Shelves
----------------

.. _homepage-shelves:

This endpoint returns the enabled shelves displayed on the AMO Homepage below the hero area.


.. http:get:: /api/v4/shelves/

    :query int page_size: Maximum number of results to return for the requested page. Defaults to 25.
    :query int page_count: The number of pages available in the pagination. 
    :query int count: The number of results for this query.
    :query string next: The URL of the next page of results.
    :query string previous: The URL of the previous page of results.
    :>json array results: The array of shelves displayed on the AMO Homepage.
    :>json string results[].title: The title of the shelf.
    :>json string results[].url: The configured URL using the shelf's endpoint and criteria; links to the shelf's returned add-ons.
    :>json string results[].endpoint: The endpoint selected for the shelf.
    :>json string results[].criteria: The criteria for the addons in the shelf.
    :>json string|null results[].footer_text: The optional text in the footer of the shelf.
    :>json string|null results[].footer_pathname: The optional pathname of the URL for the footer's text.
    :>json array results[].addons: An array of :ref:`add-ons <addon-detail-object>` or :ref:`collections <collection-detail-object>`.

---------------
Sponsored Shelf
---------------

.. _sponsored-shelf:

This endpoint returns the addons that should be shown on the sponsored shelf.
Current implementation relies on Adzerk to determine which addons are returned and in which order.


.. http:get:: /api/v4/shelves/sponsored/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query int page_size: specify how many addons should be returned.  Defaults to 6.  Note: fewer addons could be returned if there are fewer than specifed sponsored addons currently, or the Adzerk service is unavailable.
    :query string wrap_outgoing_links: If this parameter is present, wrap outgoing links through ``outgoing.prod.mozaws.net`` (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json array results: The array containing the addon results for this query.  The object is a :ref:`add-on <addon-detail-object>` as returned by :ref:`add-on search endpoint <addon-search>` with an extra field of ``events``
    :>json object results[].event_data: contains data that for different events that can be recorded.
    :>json string results[].event_data.click: the signed data payload to send to the :ref:`event endpoint <sponsored-shelf-event>` that identifies the sponsored placement clicked on.
    :>json string results[].event_data.conversion: the signed data payload to send to the :ref:`event endpoint <sponsored-shelf-event>` that identifies the conversion (install) event for the sponsored addon placement.
    :>json string impression_url: the url to ping when the contents of this sponsored shelf is rendered on screen to the user.
    :>json string impression_data: the signed data payload to send to ``impression_url`` that identifies all of the sponsored placements displayed.


---------------------------
Sponsored Shelf Impressions
---------------------------

.. _sponsored-shelf-impression:

When the sponsored shelf is displayed for the user this endpoint can be used to record the impressions.
The current implemenation forwards these impression pings to Adzerk.


.. http:post:: /api/v4/shelves/sponsored/impression/

    :form string impression_data: the signed data payload that was sent in the :ref:`sponsored shelf <sponsored-shelf>` response.


----------------------
Sponsored Shelf Events
----------------------

.. _sponsored-shelf-event:

When an item on the sponsored shelf is clicked on by the user, to navigate to the detail page, or the addon is subsequently installed from the detail page, this endpoint should be used to record that event.
The current implemenation forwards these events to Adzerk.


.. http:post:: /api/v4/shelves/sponsored/event/

    :form string data: the signed data payload that was sent in addon data in the :ref:`sponsored shelf <sponsored-shelf>` response.
    :form string type: the type of event.  Supported types are ``click`` and ``conversion``.
