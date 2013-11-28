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
            "author": "MKT Team",
            "categories": [
                "games"
            ],
            "content_ratings": {
                "ratings": {
                    "en": {"body": "ESRB", "body_label": "esrb", "rating": "Teen", "rating_label": "13", "description": "Not recommended..."},
                    "generic": {"body": "Generic", "body_label": "generic", "rating": "For ages 13+", "rating_label": "13", "description": "Not recommended..."}
                },
                "descriptors": [
                    {"label": "esrb-scary", "name": "Scary Themes", "ratings_body": "esrb"},
                    {"label": "generic-intense-violence", "name": "Intense Violence", "ratings_body": "generic"}
                ],
                "interactive_elements": [
                    {"label": "users-interact", "name": "Users Interact"},
                    {"label": "shares-location", "name": "Shares Location"},
                ]
            },
            "created": "2013-09-17T13:19:16",
            "current_version": "1.1",
            "default_locale": "en-US",
            "description": "This is the description.",
            "device_types": [
                "firefoxos"
            ],
            "homepage": "http://www.example.com/",
            "icons": {
                "16": "/tmp/uploads/addon_icons/0/24-32.png?modified=1362762723",
                "48": "/tmp/uploads/addon_icons/0/24-48.png?modified=1362762723",
                "64": "/tmp/uploads/addon_icons/0/24-64.png?modified=1362762723",
                "128": "/tmp/uploads/addon_icons/0/24-128.png?modified=1362762723"
            },
            "id": "24",
            "is_packaged": false,
            "manifest_url": "http://zrnktefoptje.test-manifest.herokuapp.com/manifest.webapp",
            "name": "Test App (zrnktefoptje)",
            "payment_account": null,
            "payment_required": false,
            "premium_type": "free",
            "previews": [
                {
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
            "status": 4,
            "support_email": "author@example.com",
            "support_url": "",
            "supported_locales": [
                "en-US",
                "es",
                "it"
            ],
            "upsell": false,
            "upsold": null,
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

    :param app_type: A string representing the app type. Can be ``hosted``,
        ``packaged`` or ``privileged``.
    :type app_type: string
    :param author: A string representing the app author.
    :type author: string
    :param categories: An array of strings representing the slugs of the
        categories the app belongs to.
    :type categories: array
    :param content_ratings: International Age Rating Coalition (IARC) content
        ratings data. It has three parts, ``ratings``, ``descriptors``, and
        ``interactive_elements``
    :type content_ratings: object
    :param content_ratings.ratings: Content ratings associated with the app by
        region. Apps that do not fall into all of the specific regions uses the
        rating keyed under "generic".
    :type content_ratings.ratings: object
    :param content_ratings.descriptors: IARC content descriptors, flags about
        the app that might affect its suitability for younger-aged users.
    :type content_ratings.descriptors: array
    :param content_ratings.interactive_elements: IARC interactive elements,
        aspects about the app relating to whether the app shares info or
        interacts with external elements.
    :type content_ratings: array
    :param created: The date the app was added to the Marketplace, in ISO 8601
        format.
    :type created: string
    :param current_version: The version number corresponding to the app's
        latest public version.
    :type current_version: string
    :param default_locale: The app's default locale, copied from the manifest.
    :type default_locale: string
    :param description: The app's description.
    :type description: string
    :param device_types: An array of strings representing the devices the app
        is marked as compatible with. Currently available devices names are
        ``desktop``, ``android-mobile``, ``android-tablet``, ``firefoxos``.
    :param homepage: The app's homepage.
    :type homepage: string
    :param icons: An object containing information about the app icons. The
        keys represent icon sizes, the values the corresponding URLs.
    :type icons: object
    :param id: The app ID.
    :type id: int
    :param is_packaged: Boolean indicating whether the app is packaged or not.
    :type is_packaged: boolean
    :param manifest_url: URL for the app manifest. If the app is not an hosted
        app, this will be a minimal manifest generated by the Marketplace.
    :param name: The app name.
    :type name: string
    :param payment_account: The path to the :ref:`payment account <payment-account-response-label>`
        being used for this app, or none if not applicable.
    :param payment_required: A payment is required for this app. It
        could be that ``payment_required`` is ``true``, but price is ``null``.
        In this case, the app cannot be bought.
    :type payment_required: boolean
    :param premium_type: One of ``free``, ``premium``, ``free-inapp``,
        ``premium-inapp``. If ``premium`` or ``premium-inapp`` the app should
        be bought, check the ``price`` field to determine if it can.
    :type premium_type: string
    :param previews: List containing the preview images for the app.
    :type previews: array
    :param previews.filetype: The mimetype for the preview.
    :type previews.filetype: string
    :param previews.id: The ID of the preview.
    :type previews.id: int
    :param previews.image_url: the absolute URL for the preview image.
    :type previews.image_url: string
    :param previews.thumbnail_url: the absolute URL for the thumbnail of the preview image.
    :type previews.image_url: string
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
    :param ratings: An object holding basic information about the app ratings.
    :type ratings: object
    :param ratings.average: The average rating.
    :type ratings.average: float
    :param ratings.count: The number of ratings.
    :type ratings.count: int
    :param regions: An list of objects containing informations about each
        region the app is available in.
    :type regions: array
    :param regions.adolescent: an adolescent region has a sufficient
        volume of data to calculate ratings and rankings independent of
        worldwide data.
    :type regions.adolescent: boolean
    :param regions.mcc: represents the region's ITU `mobile
        country code`_.
    :type regions.mcc: string|null
    :param regions.name: The region name.
    :type regions.name: string
    :param regions.slug: The region slug.
    :type regions.slug: string
    :param resource_uri: The canonical URI for this resource.
    :type resource_uri: string
    :param slug: The app slug
    :type slug: string
    :param status: The app status. See the :ref:`status table <app-statuses>`.
    :type status: int
    :param support_email: The email the app developer set for support requests.
    :type support_email: string
    :param support_url: The URL the app developer set for support requests.
    :type support_url: string
    :param supported_locales: The list of locales (as strings) supported by the
        app, according to what was set by the developer in the manifest.
    :param supported_locales: array
    :param upsell: The path to the premium app resource that this free app is
        upselling to, or null if not applicable.
    :param upsold: The path to the free app resource that
        this premium app is an upsell for, or null if not applicable.
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
    :param versions: Object representing the versions attached to this app. The
        keys represent version numbers, the values the corresponding URLs.
    :type versions: object

    .. _app-statuses:

    The possible values for app status are:

    =======  ============================
      value   status
    =======  ============================
          0   Incomplete
          2   Pending approval
          4   Fully Reviewed
          5   Disabled by Mozilla
         11   Deleted
         12   Rejected
         13   Approved but waiting
         15   Blocked
    =======  ============================

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

   See :ref:`Creating an app <app-post-label>`

.. http:put:: /api/v1/apps/app/(int:id)/

   See :ref:`Creating an app <app-put-label>`


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

    :param features: each item represents a
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

.. http:get:: /api/v1/apps/app/(int:id)/payments/debug/

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


Manifest refresh
================

.. note:: Requires authentication and a successfully created hosted app.

.. http:post:: /api/v1/apps/app/(int:id|string:slug)/refresh-manifest/

    **Response**
    :status 204: Refresh triggered.
    :status 400: App is packaged, not hosted, so no manifest to refresh.
    :status 403: Not an app you own.
    :status 404: No such app.

.. _`mobile country code`: http://en.wikipedia.org/wiki/List_of_mobile_country_codes
