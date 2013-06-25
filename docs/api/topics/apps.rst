.. _app:

===
App
===

App
===

.. http:get:: /api/v1/apps/app/

    .. note:: Requires authentication.

    Retuns a list of apps you have developed.

    **Request**

    The standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.

.. _app-response-label:

.. http:get:: /api/v1/apps/app/(int:id)|(string:slug)/

    .. note:: Does not require authentication if your app is public.

    **Response**

    An app object, see below for an example.

    :status 200: successfully completed.
    :status 403: not allowed to access this object.
    :status 404: not found.
    :status 451: resource unavailable for legal reasons.

    Example:

    .. code-block:: json

        {
            "app_type": "hosted",
            "categories": [
                3
            ],
            "content_ratings": {},
            "current_version": {
                "release_notes": null,
                "required_features": [
                    "apps",
                    "archive",
                    "audio"
                ],
                "version": "1.0"
            },
            "default_locale": "en-US",
            "description": "sdf",
            "device_types": [
                "firefoxos"
            ],
            "homepage": "",
            "icons": {
                "16": "/tmp/uploads/addon_icons/0/24-32.png?modified=1362762723",
                "48": "/tmp/uploads/addon_icons/0/24-48.png?modified=1362762723",
                "64": "/tmp/uploads/addon_icons/0/24-64.png?modified=1362762723",
                "128": "/tmp/uploads/addon_icons/0/24-128.png?modified=1362762723"
            },
            "id": "24",
            "image_assets": {
                "desktop_tile": [
                    "http://server.local/img/uploads/imageassets/0/60.png?modified=1362762724",
                    0
                ],
                "featured_tile": [
                    "http://server.local/img/uploads/imageassets/0/58.png?modified=1362762724",
                    0
                ],
                "mobile_tile": [
                    "http://server.local/img/uploads/imageassets/0/59.png?modified=1362762724",
                    0
                ]
            },
            "is_packaged": false,
            "listed_authors": [
                {
                    "name": "amckay"
                }
            ],
            "manifest_url": "http://zrnktefoptje.test-manifest.herokuapp.com/manifest.webapp",
            "name": "Test App (zrnktefoptje)",
            "premium_type": "premium",
            "previews": [
                {
                    "caption": "",
                    "filetype": "image/png",
                    "id": "37",
                    "image_url": "/tmp/uploads/previews/full/0/37.png?modified=1362762723",
                    "resource_uri": "/api/v1/apps/preview/37/",
                    "thumbnail_url": "/tmp/uploads/previews/thumbs/0/37.png?modified=1362762723"
                }
            ],
            "price": null,
            "price_locale": null,
            "privacy_policy": "/api/v1/apps/app/24/privacy/",
            "public_stats": false,
            "ratings": {
                "average": 0.0,
                "count": 0
            },
            "regions": [
                {
                    "adolescent": true,
                    "mcc": 310,
                    "name": "United States",
                    "slug": "us"
                },
                {
                    "adolescent": true,
                    "mcc": null,
                    "name": "Worldwide",
                    "slug": "worldwide"
                }
            ],
            "resource_uri": "/api/v1/apps/app/24/",
            "slug": "test-app-zrnktefoptje",
            "status": 0,
            "supported_locales": [
                "en-US",
                "es",
                "it"
            ],
            "support_email": "amckay@mozilla.com",
            "support_url": "",
            "upsell": false,
            "user": {
                "developed": false,
                "installed": false,
                "purchased": false
            }
        }

    Notes on the response.

    :param string premium_type: one of ``free``, ``premium``, ``free-inapp``,
        ``premium-inapp``. If ``premium`` or ``premium-inapp`` the app should
        be bought, check the ``price`` field to determine if it can.
    :param string|null price: will be null if the app is free. If it is a
        paid app this will b a string representing the price in the currency
        calculated for the request. If ``null``, a price cannot
        be calculated for the region and cannot be bought. Example: 1.00
    :param string|null price_locale: will be null if the app is free. If it
        is a paid app this will be a string representing the price with the
        currency formatted using the currency symbol and the locale
        representations of numbers. If ``null``, a price cannot
        be calculated for the region and cannot be bought.
        Example: "1,00 $US". For more information on this
        see :ref:`payment tiers <localized-tier-label>`.
    :param privacy_policy: The path to the privacy policy resource.
    :param boolean regions > adolescent: an adolescent region has a sufficient
        volume of data to calculate ratings and rankings independent of
        worldwide data.
    :param string|null regions > mcc: represents the region's ITU `mobile
        country code`_.
    :param list|null required_features: a list of device features required by
        this application.
    :param object user: an object representing information specific to this
        user for the app. If the user is anonymous this object will not
        be present.
    :param boolean user > developed: true if the user is a developer of the app.
    :param boolean user > installed: true if the user installed the app (this
        might differ from the device).
    :param boolean user > purchased: true if the user has purchased the app from
        the marketplace.


.. http:get:: /api/v1/apps/(int:id)|(string:slug)/privacy/

    **Response**

    :param privacy_policy: The text of the app's privacy policy.

    :status 200: successfully completed.
    :status 403: not allowed to access this object.
    :status 404: not found.
    :status 451: resource unavailable for legal reasons.

.. http:delete:: /api/v1/apps/app/(int:id)/

   .. note:: Requires authentication.

   **Response**

   :status 204: successfully deleted.

.. http:post:: See :ref:`Creating an App <app-post-label>`
.. http:put::  See :ref:`Creating an App <app-put-label>`

Payments
========

.. note:: Requires authentication and a successfully created app.

.. http:get:: /api/v1/apps/app/(int:id)/payments/

    **Response**

    .. code-block:: json

    :param upsell: URL to the upsell of the app.
    :param account: URL to the app payment account.
    :status 200: sucessfully completed.


For more information on these, see the payments documentation.

.. _`mobile country code`: http://en.wikipedia.org/wiki/List_of_mobile_country_codes
