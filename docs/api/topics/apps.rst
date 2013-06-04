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

    :param string|null price: will be null if the app is free. If it is a
        paid app this will b a string representing the price in the currency
        calculated for the request. Example: 1.00
    :param string|null price_locale: will be null if the app is free. If it
        is a paid app this will be a string representing the price with the
        currency formatted using the currency symbol and the locale
        representations of numbers. Example: "1,00 $US". For more information
        on this see :ref:`payment tiers <localized-tier-label>`.
    :param boolean regions > adolescent: an adolescent region has a sufficient
        volume of data to calculate ratings and rankings independent of
        worldwide data.
    :param string|null regions > mcc: represents the region's ITU `mobile
        country code`_.
    :param object user: an object representing information specific to this
        user for the app. If the user is anonymous this object will not
        be present.
    :param privacy_policy: The path to the privacy policy resource.
    :param boolean user > developed: true if the user is a developer of the app.
    :param boolean user > installed: true if the user installed the app (this might differ from
        the device).
    :param boolean user > purchased: true if the user has purchased the app from
        the marketplace.

.. http:get:: /api/v1/apps/(int:id)|(string:slug)/privacy/

    **Response**

    :param privacy_policy: The text of the app's privacy policy.

    :status 200: successfully completed.
    :status 403: not allowed to access this object.
    :status 404: not found.
    :status 451: resource unavailable for legal reasons.


.. _app-post-label:

.. http:post:: /api/v1/apps/app/

    .. note:: Requires authentication and a successfully validated manifest.

    .. note:: You must accept the `terms of use`_ before submitting apps.

    .. note:: This method is throttled at 10 requests/day.

    **Request**

    :param manifest: the id of the validated manifest.

    Or for a *packaged app*

    :param upload: the id of the validated packaged app.

    **Response**

    :param: An :ref:`apps <app-response-label>`.
    :status code: 201 successfully created.

.. _app-put-label:

.. http:put:: /api/v1/apps/app/(int:id)/

    **Request**

    :param required name: the title of the app. Maximum length 127 characters.
    :param required summary: the summary of the app. Maximum length 255 characters.
    :param required categories: a list of the categories, at least two of the
        category ids provided from the category api (see below).
    :param optional description: long description. Some HTML supported.
    :param required privacy_policy: your privacy policy. Some HTML supported.
    :param optional homepage: a URL to your apps homepage.
    :param optional support_url: a URL to your support homepage.
    :param required support_email: the email address for support.
    :param required device_types: a list of the device types at least one of:
        `desktop`, `mobile`, `tablet`, `firefoxos`. `mobile` and `tablet` both
        refer to Android mobile and tablet. As opposed to Firefox OS.
    :param required regions: a list of regions this app should be
        listed in, expressed as country codes or 'worldwide'.
    :param required premium_type: One of `free`, `premium`,
        `free-inapp`, `premium-inapp`, or `other`.
    :param optional price: The price for your app as a string, for example
        "0.10". Required for `premium` or `premium-inapp` apps.
    :param optional payment_account: The path for the
        :ref:`payment account <payment-account-label>` resource you want to
        associate with this app.
    :param optional upsold: The path to the free app resource that
        this premium app is an upsell for.

    **Response**

    :status 202: successfully updated.


.. http:delete:: /api/v1/apps/app/(int:id)/

   .. note:: Requires authentication.

   **Response**

   :status 204: successfully deleted.

Payments
========

.. note:: Requires authentication and a successfully created app.

.. http:get:: /api/v1/apps/app/(int:id)/payments/

    **Response**

    .. code-block:: json

    :param upsell: URL to the upsell of the app.
    :status 200: sucessfully completed.

.. http:post:: /api/v1/developers/upsell/(int:id)/

    Creates an upsell relationship between two apps, a free and premium one.
    Send the URLs for both apps in the post to create the relationship.

    **Request**

    :param free: URL to the free app.
    :param premium: URL to the premium app.

    **Response**

    :status 201: sucessfully created.

.. http:get:: /api/v1/developers/upsell/(int:id)/

    **Response**

    .. code-block:: json

        {"free": "/api/v1/apps/app/1/",
         "premium": "/api/v1/apps/app/2/"}

    :param free: URL to the free app.
    :param premium: URL to the premium app.

.. http:patch:: /api/v1/developers/upsell/(int:id)/

    Alter the upsell from free to premium by passing in new free and premiums.

    **Request**

    :param free: URL to the free app.
    :param premium: URL to the premium app.

    **Response**

    :status 200: sucessfully altered.

.. http:delete:: /api/v1/developers/upsell/(int:id)/

    To delete the upsell relationship.

    **Response**

    :status 204: sucessfully deleted.

Screenshots or videos
=====================

.. note:: Requires authentication and a successfully created app.

.. _screenshot-post-label:

.. http:post:: /api/v1/apps/preview/?app=(int:app_id)

    **Request**

    :param position: the position of the preview on the app. We show the
        previews in the order given.
    :param file: a dictionary containing the appropriate file data in the upload field.
    :param file type: the content type.
    :param file name: the file name.
    :param file data: the base 64 encoded data.

    .. note:: There is currently a restriction of 5MB on file uploads through
        the API.

    **Response**

    A :ref:`screenshot <screenshot-response-label>` resource.

    :status 201: successfully completed.
    :status 400: error processing the form.

.. _screenshot-response-label:

.. http:get:: /api/v1/apps/preview/(int:preview_id)/

    **Response**

    Example:

    .. code-block:: json

        {
            "addon": "/api/v1/apps/app/1/",
            "id": 1,
            "position": 1,
            "thumbnail_url": "/img/uploads/...",
            "image_url": "/img/uploads/...",
            "filetype": "image/png",
            "resource_uri": "/api/v1/apps/preview/1/"
            "caption": "Awesome screenshot"
        }

.. http:delete:: /api/v1/apps/preview/(int:preview_id)/

    **Response**

    :status 204: successfully deleted.

Enabling an App
===============

.. note:: Requires authentication and a successfully created app.

.. _enable-patch-label:

.. http:patch:: /api/v1/apps/status/(int:app_id)/

    **Request**

    :params (optional) status: a status you'd like to move the app too (see
        below).
    :params (optional) disabled_by_user: can be `true` or `false`

    **Response**

    :status 200: successfully completed.
    :status 400: something prevented the transition.


Key statuses are:

  * `incomplete`: incomplete
  * `pending`: pending
  * `public`: public
  * `waiting`: waiting to be public

Valid transitions that users can initiate are:

* *incomplete* to *pending*: call this once your app has been completed and it
  will be added to the Marketplace review queue. This can only be called if all
  the required data is there. If not, you'll get an error containing the
  reason. For example:

    .. code-block:: json

        {
            "error_message": {
                "status": [
                    "You must provide a support email.",
                    "You must provide at least one device type.",
                    "You must provide at least one category.",
                    "You must upload at least one screenshot or video."
                ]
            }
        }

* Once reviewed by the Marketplace review team, the app will be to *public* or
  *waiting to be public*.
* *waiting* to *public*: occurs when the app has been reviewed, but not yet
  been made public.
* *disabled_by_user*: by changing this value from `True` to `False` you can
  enable or disable an app.

.. _`terms of use`: https://marketplace.firefox.com/developers/terms
.. _`mobile country code`: http://en.wikipedia.org/wiki/List_of_mobile_country_codes
