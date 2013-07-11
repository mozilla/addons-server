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
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.
    :type objects: array

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
            "current_version": "1.1",
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
            "payment_required": false,
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
            },
            "versions": {
                "1.0": "/api/v1/apps/versions/7012/",
                "1.1": "/api/v1/apps/versions/7930/"
            }
        }

    Notes on the response.

    :param payment_required: A payment is required for this app. It
        could be that ``payment_required`` is ``true``, but price is ``null``.
        In this case, the app cannot be bought.
    :type payment_required: boolean
    :param premium_type: one of ``free``, ``premium``, ``free-inapp``,
        ``premium-inapp``. If ``premium`` or ``premium-inapp`` the app should
        be bought, check the ``price`` field to determine if it can.
    :type premium_type: string
    :param price: If it is a paid app this will be a string representing
        the price in the currency calculated for the request. If ``0.00`` then
        no payment is required, but the app requires a receipt. If ``null``, a
        price cannot be calculated for the region and cannot be bought.
        Example: 1.00
    :type price: string|null
    :param price_locale: If it is a paid app this will be a string representing
        the price with the currency formatted using the currency symbol and
        the locale representations of numbers. If ``0.00`` then no payment is
        required, but the app requires a receipt. If ``null``, a price cannot
        be calculated for the region and cannot be bought.
        Example: "1,00 $US". For more information on this
        see :ref:`payment tiers <localized-tier-label>`.
    :type price_locale: string|null
    :param privacy_policy: The path to the privacy policy resource.
    :type privacy_policy: string
    :param regions.adolescent: an adolescent region has a sufficient
        volume of data to calculate ratings and rankings independent of
        worldwide data.
    :type regions.adolescent: boolean
    :param regions.mcc: represents the region's ITU `mobile
        country code`_.
    :type regions.mcc: string|null
    :param required_features: a list of device features required by
        this application.
    :type required_features: list|null
    :param optional upsold: The path to the free app resource that
        this premium app is an upsell for.
    :param user: an object representing information specific to this
        user for the app. If the user is anonymous this object will not
        be present.
    :type user: object
    :param user.developed: true if the user is a developer of the app.
    :type user.developed: boolean
    :param user.installed: true if the user installed the app (this
        might differ from the device).
    :type user.installed: boolean
    :param user.purchased: true if the user has purchased the app from
        the marketplace.
    :type user.purchased: boolean

.. http:get:: /api/v1/apps/(int:id)|(string:slug)/privacy/

    **Response**

    :param privacy_policy: The text of the app's privacy policy.
    :type privacy_policy: string

    :status 200: successfully completed.
    :status 403: not allowed to access this object.
    :status 404: not found.
    :status 451: resource unavailable for legal reasons.

.. http:delete:: /api/v1/apps/app/(int:id)/

   .. note:: Requires authentication.

   **Response**

   :status 204: successfully deleted.

.. http:post:: /api/v1/apps/app/

   See :ref:`Creating an App <app-post-label>`

.. http:put:: /api/v1/apps/app/(int:id)/

   See :ref:`Creating an App <app-put-label>`


Versions
========

.. http:get:: /api/v1/apps/versions/(int:id)/

    Retrieves data for a specific version of an application.

    **Response**

    :status 200: successfully completed.
    :status 404: not found.

    Example:

    .. code-block:: json

        {
            "app": "/api/v1/apps/app/7/",
            "developer_name": "Cee's Vans",
            "features": [
                "apps",
                "push"
            ],
            "is_current_version": true,
            "release_notes": "New and improved!",
            "version": "1.1"
        }

    :param is_current_version: indicates whether this is the most recent
        public version of the application.
    :type is_current_version: boolean
    :param features: each item represents a
        :ref:`device feature <features>` required to run the application.
    :type features: array

.. http:patch:: /api/v1/apps/versions/(int:id)/

    Update data for a specific version of an application.

    .. note:: Requires authentication.

    **Request**

    Example:

    .. code-block:: json

        {
            "developer_name": "Cee's Vans",
            "features": [
                "apps",
                "mp3",
                "push"
            ]
        }

    :param object features: each item represents a
        :ref:`device feature <features>` required to run the application.
        Features not present are assumed not to be required.
    :type features: array

    **Response**

    Returns the updated JSON representation

    :status 200: sucessfully altered.
    :status 403: not allowed to modify this version's app.
    :status 404: not found.


Payments
========

.. note:: Requires authentication and a successfully created app.

.. http:get:: /api/v1/apps/app/(int:id)/payments/

    Gets information about the payments of an app, including the payment
    account.

    **Response**

    :param upsell: URL to the :ref:`upsell of the app <upsell-response-label>`.
    :type upsell: string
    :param account: URL to the :ref:`app payment account <payment-account-response-label>`.
    :type account: string
    :status 200: sucessfully completed.

.. http:post:: /api/v1/apps/app/(int:id)/payments/status/

    Queries the Mozilla payment server to check that the app is ready to be
    sold. This would normally be run at the end of the payment flow to ensure
    that the app is setup correctly. The Mozilla payment server records the
    status of this check.

    **Request**

    Empty.

    **Response**

    .. code-block:: json

        {
            "bango": {
                "status": "passed",
                "errors": []
            }
        }

    :param status: `passed` or `failed`.
    :type status: string
    :param errors: an array of errors as string. Currently empty, reserved for
        future use.
    :type errors: array of strings.

    :status 200: successfully completed.
    :status 400: app is not valid for checking, examine response content.
    :status 403: not allowed.

.. note:: The Transaction:Debug permission is required.

.. http:get:: /api/v1/apps/api/(int:id)/payments/debug/

    Returns useful debug information about the app, suitable for marketplace
    developers and integrators. Output is truncated below and is subject
    to change.

    **Response**

    .. code-block:: json

        {
            "bango": {
                "environment": "test"
            },
        }

    :status 200: successfully completed.
    :status 400: app is not valid for checking, examine response content.
    :status 403: not allowed.

.. _`mobile country code`: http://en.wikipedia.org/wiki/List_of_mobile_country_codes
