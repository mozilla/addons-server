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
            "premium_type": "premium",
            "support_email": "amckay@mozilla.com",
            "content_ratings": {},
            "current_version": {
                "version": "1.0",
                "release_notes": null
            },
            "manifest_url": "http://zrnktefoptje.test-manifest.herokuapp.com/manifest.webapp",
            "id": "24",
            "ratings": {
                "count": 0,
                "average": 0.0
            },
            "app_type": "hosted",
            "icons": {
                "128": "/tmp/uploads/addon_icons/0/24-128.png?modified=1362762723",
                "64": "/tmp/uploads/addon_icons/0/24-64.png?modified=1362762723",
                "48": "/tmp/uploads/addon_icons/0/24-48.png?modified=1362762723",
                "16": "/tmp/uploads/addon_icons/0/24-32.png?modified=1362762723"
            },
            "support_url": "",
            "homepage": "",
            "image_assets": {
                "featured_tile": [
                    "http://server.local/img/uploads/imageassets/0/58.png?modified=1362762724",
                    0
                ],
                "mobile_tile": [
                    "http://server.local/img/uploads/imageassets/0/59.png?modified=1362762724",
                    0
                ],
                "desktop_tile": [
                    "http://server.local/img/uploads/imageassets/0/60.png?modified=1362762724",
                    0
                ]
            },
            "public_stats": false,
            "status": 0,
            "privacy_policy": "sdfsdf",
            "is_packaged": false,
            "description": "sdf",
            "listed_authors": [
                {
                    "name": "amckay"
                }
            ],
            "price": null,
            "price_locale": null,
            "previews": [
                {
                    "filetype": "image/png",
                    "caption": "",
                    "thumbnail_url": "/tmp/uploads/previews/thumbs/0/37.png?modified=1362762723",
                    "image_url": "/tmp/uploads/previews/full/0/37.png?modified=1362762723",
                    "id": "37",
                    "resource_uri": "/api/v1/apps/preview/37/"
                }
            ],
            "user": {
                "owns": false
            },
            "slug": "test-app-zrnktefoptje",
            "categories": [
                3
            ],
            "name": "Test App (zrnktefoptje)",
            "device_types": [
                "firefoxos"
            ],
            "summary": "Test manifest",
            "upsell": false,
            "resource_uri": "/api/v1/apps/app/24/"
        }

    Notes on the response:

    * price: will be null if the app is free. If it is a paid app this will be
      a string representing the price in the currency calculated for the
      request. Example: 1.00
    * price_locale: will be null if the app is free. If it is a paid app this
      will be a string representing the price with the currency formatted using
      the currency symbol and the locale representations of numbers. Example:
      "1,00 $US". For more information on this see :ref:`payment tiers
      <localized-tier-label>`.

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
    :param required payment_type: only choice at this time is `free`.

    **Response**

    :status 201: successfully updated.


.. http:delete:: /api/v1/apps/app/(int:id)/

   .. note:: Requires authentication.

   **Response**

   :status 204: successfully deleted.




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
