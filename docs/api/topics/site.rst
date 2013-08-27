.. _site:

====
Site
====

Configuration about the site.

Categories
==========

.. note:: The URL for this API will be moving.

.. http:get:: /api/v1/apps/category/

    Returns a list of categories available on the marketplace.

    **Request**

    Standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`categories <category-response-label>`.
    :type objects: array
    :status 200: successfully completed.


.. _category-response-label:

.. http:get:: /api/v1/apps/category/(int:id)/

    Returns a category.

    **Response**

    .. code-block:: json

        {
            "id": 1,
            "name": "Games",
            "resource_uri": "/api/v1/apps/category/1/",
            "slug": "games"
        }

Carriers
========

.. http:get:: /api/v1/services/carrier/

    Returns a list of possible carriers for apps.

    **Response**


    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`carriers <carrier-response-label>`.
    :type objects: array
    :status 200: successfully completed.

.. _carrier-response-label:

.. http:get:: /api/v1/services/carrier/<slug>/

    Returns a carrier.

    **Request**

    Standard :ref:`list-query-params-label`.

    **Response**

    .. code-block:: json

        {
            "id": "1",
            "name": "PhoneORama",
            "resource_uri": "/api/v1/services/carrier/phoneorama/",
            "slug": "phoneorama"
        }

.. _regions:

Regions
=======

.. http:get:: /api/v1/services/region/

    Returns a list of possible regions for apps.

    **Response**


    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`regions <region-response-label>`.
    :type objects: array
    :status 200: successfully completed.

.. _region-response-label:

.. http:get:: /api/v1/services/region/<slug>/

    Returns a region.

    **Request**

    Standard :ref:`list-query-params-label`.

    **Response**

    .. code-block:: json

        {
            "id": "1",
            "name": "Appistan",
            "resource_uri": "/api/v1/services/region/ap/",
            "slug": "ap",
            "default_currency": "USD",
            "default_language": "en-AP",
        }

Configuration
=============

.. http:get:: /api/v1/services/config/site/

    Returns information about how the marketplace is configured. Not all
    settings and configuration options are returned - only a subset. This
    subset will change as features in the site change. The list of results
    should not be relied upon to stay consistent.

    **Response**

    :param version: the git commit number of the deployment.
    :type version: string|null
    :param settings: a subset of useful site settings.
    :type settings: object
    :param flags: a subset of useful runtime configuration settings.
    :type flags: object

    Example:

    .. code-block:: json

        {
            "flags": {
                "allow-b2g-paid-submission": true,
                "allow-refund": true,
                "in-app-sandbox": false
            },
            "resource_uri": "",
            "settings": {
                "SITE_URL": "http://z.mozilla.dev"
            },
            "version": null
        }
