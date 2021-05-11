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


.. http:get:: /api/v5/hero/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :>json object primary: A :ref:`primary hero shelf <primary-hero-shelf>`.
    :>json object secondary: A :ref:`secondary hero shelf <secondary-hero-shelf>`.


--------------------
Primary Hero Shelves
--------------------

.. _primary-hero-shelf:

This endpoint returns all enabled primary hero shelves.  As there will only ever be a
small number of shelves this endpoint is not paginated.


.. http:get:: /api/v5/hero/primary/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query boolean all: return all shelves - both enabled and disabled.  To be used internally to generate .po files containing the strings defined by the content team.
    :query string raw: If this parameter is present, don't localise description or fall-back to addon metadata.  To be used internally to generate .po files containing the strings defined by the content team.
    :>json array results: The array containing the results for this query.
    :>json object results[].gradient: The background colors used for the gradient.
    :>json string results[].gradient.start: The starting color name for gradient - typically top or left. The name is from the `photon color variables <https://github.com/FirefoxUX/photon-colors/blob/master/photon-colors.scss>`_.
    :>json string results[].gradient.end: The ending color name for gradient - typically bottom or right. The name is from the `photon color variables <https://github.com/FirefoxUX/photon-colors/blob/master/photon-colors.scss>`_.
    :>json string|null results[].featured_image: The image used to illustrate the item, if set.
    :>json object|null results[].description: The description for this item, if any. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json object results[].addon: The :ref:`add-on <addon-detail-object>` for this item if the addon is hosted on AMO. Either this field or ``external`` will be present.  Only a subset of fields are present: ``id``, ``authors``, ``average_daily_users``, ``current_version`` (with only the ``id``, ``compatibility``, ``is_strict_compatibility_enabled`` and ``files`` fields present), ``guid``, ``icon_url``, ``name``, ``ratings``, ``previews``, ``promoted``, ``slug``, ``theme_data``, ``type``, and ``url``.
    :>json object results[].external: The :ref:`add-on <addon-detail-object>` for this item if the addon is externally hosted. Either this field or ``addon`` will be present.  Only a subset of fields are present: ``id``, ``guid``, ``homepage``, ``name`` and ``type``.


----------------------
Secondary Hero Shelves
----------------------

.. _secondary-hero-shelf:

This endpoint returns all enabled secondary hero shelves.  As there will only ever be a
small number of shelves - and likely only one - this endpoint is not paginated.


.. http:get:: /api/v5/hero/secondary/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :query boolean all: return all shelves - both enabled and disabled.  To be used internally to generate .po files containing the strings defined by the content team.
    :>json array results: The array containing the results for this query.
    :>json object|null results[].headline: The headline for this item. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json object|null results[].description: The description for this item. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json object|null results[].cta: The optional call to action link and text to be displayed with the item.
    :>json string results[].cta.url: The url the call to action would link to.
    :>json string results[].cta.outgoing: (v5+ only) url wrapped with outgoing (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json object|null results[].cta.text: The call to action text. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json array results[].modules: The modules for this shelf.  Should always be 3.
    :>json string results[].modules[].icon: The icon used to illustrate the item.
    :>json object|null results[].modules[].description: The description for this item. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json object|null results[].modules[].cta: The optional call to action link and text to be displayed with the item.
    :>json string results[].modules[].cta.url: The url the call to action would link to.
    :>json string results[].modules[].cta.outgoing: (v5+ only) url wrapped with outgoing (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json object|null results[].modules[].cta.text: The call to action text. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).


----------------
Homepage Shelves
----------------

.. _homepage-shelves:

This endpoint returns the shelves to display on the AMO Homepage.
A single, randomly selected, primary hero shelf and a single, randomly selected secondary
hero shelf is returned, along with the enabled shelves. As there will only ever be a
small number of shelves this endpoint is not paginated.


.. http:get:: /api/v5/shelves/

    :query string lang: Activate translations in the specific language for that query. (See :ref:`translated fields <api-overview-translations>`)
    :>json array results: The array of shelves displayed on the AMO Homepage.
    :>json object|null results[].title: The title of the shelf. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json string results[].url: The configured URL using the shelf's endpoint and criteria; links to the shelf's returned add-ons.
    :>json string results[].endpoint: The :ref:`endpoint type <shelf-endpoint-type>` selected for the shelf.
    :>json string results[].addon_type: The :ref:`add-on type <addon-detail-type>` selected for the shelf.
    :>json string results[].criteria: The criteria for the addons in the shelf.
    :>json object|null results[].footer: The optional footer to be displayed with the shelf.
    :>json string results[].footer.url: The optional url for the footer text.
    :>json string results[].footer.outgoing: url wrapped with outgoing (See :ref:`Outgoing Links <api-overview-outgoing>`)
    :>json object|null results[].footer.text: The optional text in the footer of the shelf. (See :ref:`translated fields <api-overview-translations>`.  Note: when ``lang`` is not specified, not all locales will be returned, unlike other translated fields).
    :>json array results[].addons: An array of :ref:`add-ons <addon-detail-object>`.
    :>json object primary: A :ref:`primary hero shelf <primary-hero-shelf>`.
    :>json object secondary: A :ref:`secondary hero shelf <secondary-hero-shelf>`.

.. _shelf-endpoint-type:

    Possible values for the ``endpoint`` field:

    ==============  ====================================================
             Value  Description
    ==============  ====================================================
            search  an :ref:`addon search<addon-search>`
       collections  a mozilla :ref:`collection<collection-addon-list>`.
                    The collection slug will be in ``criteria``
    ==============  ====================================================


----------------------------------
Homepage Shelves Editorial Content
----------------------------------

.. _homepage-shelves-editorial:

This endpoint allows you to fetch all editorial content for Homepage Shelves.
This is used internally to generate .po files containing the strings defined by the content team.


.. http:get:: /api/v5/shelves/editorial

    :>json array results: The array of shelves displayed on the AMO Homepage.
    :>json string|null results[].title: The title of the shelf.
    :>json string|null results[].footer_text: The optional text in the footer of the shelf.
