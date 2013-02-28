.. _submission:

======================
Submission API
======================

Adding an app follows a few steps, roughly analgous to the flow in a browser.
Validate your app, add it in, update it with the various data and
then request review.

Validate
========

.. note:: The validation does not require you to be authenticated, however you
    cannot create apps from those validations. To validate and submit an app
    you must be authenticated for both steps.

To validate a hosted app::

        POST /api/apps/validation/
        {"manifest": "http://test.app.com/manifest"}

To validate a packaged app, send the appropriate file data in the upload field.
File data is a dictionary of name, type (content type) and the base 64 encoded
data. For example::

        POST /api/apps/validation/
        {"upload": {"type": "application/foo",
                    "data": "UEsDBAo...gAAAAA=",
                    "name": "mozball.zip"}}

This will return the result of the validation as below. Hosted apps are done
immediately but packaged apps are queued. Clients will have to poll the results
URL until the validation has been processed.

To query the result::

        GET /api/apps/validation/123/

This will return the status of the validation. An example of a validation not processed yet::

        {"id": "123",
         "processed": false,
         "resource_uri": "/api/apps/validation/123/",
         "valid": false,
         "validation": ""}

Example of a validation processed and good::

        {"id": "123",
         "processed": true,
         "resource_uri": "/api/apps/validation/123/",
         "valid": true,
         "validation": ""}

Example of a validation processed but with an error::

        {"id": "123",
         "processed": true,
         "resource_uri": "/api/apps/validation/123/",
         "valid": false,
         "validation": {
           "errors": 1, "messages": [{
             "tier": 1,
             "message": "Your manifest must be served with the HTTP header \"Content-Type: application/x-web-app-manifest+json\". We saw \"text/html; charset=utf-8\".",
             "type": "error"
           }],
        }}

Create
======

.. note:: Requires authentication and a successfully validated manifest.

To create an app with your validated manifest the body data should contain the
manifest id from the validate call and other data in JSON::


        POST /api/apps/app/
        {"manifest": "123"}

If you'd like to create a successfully validation packaged app, use upload
instead of manifest::

        POST /api/apps/app/
        {"upload": "123"}

If the creation succeeded you'll get a 201 status back. This will return the id
of the app on the marketplace as a slug. The marketplace will complete some of
the data using the manifest and return values so far::

        {"categories": [],
         "description": null,
         "device_types": [],
         "homepage": null,
         "id": 1,
         "manifest": "0a650e5e4c434b5cb60c5495c0d88a89",
         "name": "MozillaBall",
         "premium_type": "free",
         "privacy_policy": null,
         "resource_uri": "/api/apps/app/1/",
         "slug": "mozillaball",
         "status": 0,
         "summary": "Exciting Open Web development action!",
         "support_email": null,
         "support_url": null
        }

Fields:

* `manifest` (required): the id of the manifest returned from verfication.

Update
======

.. note:: Requires authentication and a successfully created app.

Put your app to update it. The body contains JSON for the data to be posted::

        PUT /api/apps/app/<app id>/

These are the fields for the creation and update of an app. These will be
populated from the manifest if specified in the manifest. Will return a 202
status if the app was successfully updated.

Fields:

* `name` (required): the title of the app. Maximum length 127 characters.
* `summary` (required): the summary of the app. Maximum length 255 characters.
* `categories` (required): a list of the categories, at least two of the
  category ids provided from the category api (see below).
* `description` (optional): long description. Some HTML supported.
* `privacy_policy` (required): your privacy policy. Some HTML supported.
* `homepage` (optional): a URL to your apps homepage.
* `support_url` (optional): a URL to your support homepage.
* `support_email` (required): the email address for support.
* `device_types` (required): a list of the device types at least one of:
  'desktop', 'mobile', 'tablet', 'firefoxos'. 'mobile' and 'tablet' both refer
  to Android mobile and tablet. As opposed to Firefox OS.
* `payment_type` (required): only choice at this time is 'free'.

Example body data::

        {"privacy_policy": "wat",
         "name": "mozball",
         "device_types": ["desktop-1"],
         "summary": "wat...",
         "support_email": "a@a.com",
         "categories": [1L, 2L],
         "previews": []
         }

Previews will be list of URLs pointing to the screenshot API.

List
====

.. note:: Requires authentication.

To get a list of the apps you have available::

        GET /api/apps/app/

This will return a list of all the apps the user is allowed to access::

        {"meta": {"limit": 20,
                  "next": null,
                  "offset": 0,
                  "previous": null,
                  "total_count": 2},
         "objects": [
                {"categories": [1L],
                 "resource_uri": "/api/apps/app/4/"
                 ...]}
        }

Get
===

.. note:: Requires authentication if the app is not public.

To get an individual app, use the `resource_uri` from the list::

        GET /api/apps/app/4/

This will return::

        {"resource_uri": "/api/apps/app/4/",
         "slug": "mozillaball",
         "summary": "Exciting Open Web development action!",
         ...}

Status
======

.. note:: Requires authentication and a successfully created app.

To view details of an app, including its review status::

        GET /api/apps/app/<app id>/

Returns the status of the app::

        {"slug": "your-test-app",
         "name": "My cool app",
         ...}

Screenshots or videos
=====================

.. note:: Requires authentication and a successfully created app.

These can be added as seperate API calls. There are limits in the marketplace
for what screenshots and videos can be accepted. There is a 5MB limit on file
uploads through the API (for more use the web interface).

Create
++++++

Create a screenshot or video::

        POST /api/apps/preview/?app=<app id>

The body should contain the screenshot or video to be uploaded in the following
format::

        {"position": 1, "file": {"type": "image/jpg", "data": "iVBOR..."}}

Fields:

* `file`: a dictionary containing two fields:
  * `type`: the content type
  * `data`: base64 encoded string of the preview to be added
* `position`: the position of the preview on the app. We show the previews in
  order

This will return a 201 if the screenshot or video is successfully created. If
not we'll return the reason for the error.

Returns the screenshot id::

        {"position": 1, "thumbnail_url": "/img/uploads/...",
         "image_url": "/img/uploads/...", "filetype": "image/png",
         "resource_uri": "/api/apps/preview/1/"}

Get
+++

Get information about the screenshot or video::


        GET /api/apps/preview/<preview id>/

Returns::

        {"addon": "/api/apps/app/1/", "id": 1, "position": 1,
         "thumbnail_url": "/img/uploads/...", "image_url": "/img/uploads/...",
         "filetype": "image/png", "resource_uri": "/api/apps/preview/1/"}


Delete
++++++

Delete a screenshot of video::

        DELETE /api/apps/preview/<preview id>/

This will return a 204 if the screenshot has been deleted.

Enabling an App
===============

.. note:: Requires authentication and a successfully created app.

Once all the data has been completed and at least one screenshot created, you
can push the app to the review queue::

        PATCH /api/apps/status/<app id>/
        {"status": "pending"}

* `status` (optional): key statuses are

  * `incomplete`: incomplete
  * `pending`: pending
  * `public`: public
  * `waiting`: waiting to be public

* `disabled_by_user` (optional): `True` or `False`.

Valid transitions that users can initiate are:

* *waiting to be public* to *public*: occurs when the app has been reviewed,
  but not yet been made public.
* *incomplete* to *pending*: call this once your app has been completed and it
  will be added to the Marketplace review queue. This can only be called if all
  the required data is there. If not, you'll get an error containing the
  reason. For example::

        PATCH /api/apps/status/<app id>/
        {"status": "pending"}

        Status code: 400
        {"error_message":
                {"status": ["You must provide a support email.",
                            "You must provide at least one device type.",
                            "You must provide at least one category.",
                            "You must upload at least one screenshot or video."]}}

* *disabled_by_user*: by changing this value from `True` to `False` you can
  enable or disable an app.
