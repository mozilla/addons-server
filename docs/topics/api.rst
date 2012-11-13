.. _api:

======================
Marketplace API
======================

This API is for Apps. There is a seperate set of `APIs for Add-ons`_.

Overall notes
-------------

Authentication
==============

Not all APIs require authentication. Each API will note if it needs
authentication.

Currently only two legged OAuth authentication is supported. This is focused on
clients who would like to create multiple apps on the app store from an end
point.

When you are first developing your API to communicate with the Marketplace, you
should use the staging server to test your API. When it's complete, you can
request a production token.

Staging server
++++++++++++++

The staging server is at https://marketplace.allizom.org.

We make no guarantees on the uptime of the staging server. Also data may be
occasionally purged, causing the deletion of apps and tokens.

1. Login to the staging server using Persona:
   https://marketplace.allizom.org/login

2. Once logged in, read and accept the terms of service for the Marketplace
   at: https://marketplace.allizom.org/developers/terms

3. Generate a new key at: https://marketplace.allizom.org/developers/api

Production server
+++++++++++++++++

The production server is at https://marketplace.firefox.com.

1. Login to the production server using Persona:
   https://marketplace.firefox.com

2. Once logged in, read and accept the terms of service for the Marketplace
   at: https://marketplace.firefox.com/developers/terms

3. You cannot generate your own tokens. Please contact a `Marketplace
   representative`_.

Using OAuth Tokens
^^^^^^^^^^^^^^^^^^

Once you've got your token, you will need to ensure that the OAuth token is
sent correctly in each request.

To correctly sign an OAuth request, you'll need the OAuth consumer key and
secret and then sign the request using your favourite OAuth library. An example
of this can be found in the `example marketplace client`_.

Example headers (new lines added for clarity)::

        Content-type: application/json
        Authorization: OAuth realm="",
                       oauth_body_hash="2jm...",
                       oauth_nonce="06731830",
                       oauth_timestamp="1344897064",
                       oauth_consumer_key="some-consumer-key",
                       oauth_signature_method="HMAC-SHA1",
                       oauth_version="1.0",
                       oauth_signature="Nb8..."

If requests are failing and returning a 401 response, then there will likely be
a reason contained in the response. For example::

        {u'reason': u'Terms of service not accepted.'}

Errors
======

Marketplace will return errors as JSON with the appropriate status code.

Data errors
+++++++++++

If there is an error in your data, a 400 status code will be returned. There
can be multiple errors per field. Example::

        {
          "error_message": {
            "manifest": ["This field is required."]
          }
        }

Other errors
++++++++++++

The appropriate HTTP status code will be returned.

Verbs
=====

This follows the order of the `django-tastypie`_ REST verbs, a PUT for an update and POST for create.

Response
========

All responses are in JSON.

Adding an app to the Marketplace
--------------------------------

Adding an app follows a few steps, roughly analgous to the flow in a browser.
Basically, validate your app, add it in, update it with the various data and
then request review.

Validate
========

This API requires authentication.

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

Then you get the result::

        GET /api/apps/validation/123/

This will return the status of the validation. Validation not processed yet::

        {"id": "123",
         "processed": false,
         "resource_uri": "/api/apps/validation/123/",
         "valid": false,
         "validation": ""}

Validation processed and good::

        {"id": "123",
         "processed": true,
         "resource_uri": "/api/apps/validation/123/",
         "valid": true,
         "validation": ""}

Validation processed and an error::

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

You can always check the validation later::

        GET /api/apps/validation/123/

Create
======

This API requires authentication and a successfully validated manifest. To
create an app with your validated manifest. Body data should contain the
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

* manifest (required): the id of the manifest returned from verfication.

Update
======

This API requires authentication and a successfully created app::

        PUT /api/apps/app/<app id>/

The body contains JSON for the data to be posted.

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
  'desktop', 'mobile', 'tablet'.
* `payment_type` (required): only choice at this time is 'free'.

Example body data::

        {"privacy_policy": "wat",
         "name": "mozball",
         "device_types": ["desktop-1"],
         "summary": "wat...",
         "support_email": "a@a.com",
         "categories": [1L, 2L],
         "previews": [],
         }

Previews will be list of URLs pointing to the screenshot API.

List
====

To get a list of the apps you have available::

        GET /api/apps/app/

This will return a list of all the apps the user is allowed to access::

        {"meta": {"limit": 20,
                  "next": null,
                  "offset": 0,
                  "previous": null,
                  "total_count": 2},
         "objects": [{"categories": [1L], "resource_uri": "/api/apps/app/4/"
                      ...and the rest of the object]}

Get
===

To get an individual app, use the `resource_uri` from the list::

        GET /api/apps/app/4/

This will return::

        {"resource_uri": "/api/apps/app/4/", "slug": "mozillaball",
         "summary": "Exciting Open Web development action!",
         ...and the rest of the object}

Status
======

This API requires authentication and a successfully created app.

To view details of an app, including its review status::

        GET /api/apps/app/<app id>/

Returns the status of the app::

        {"slug": "your-test-app",
         "name": "My cool app",
         ...}

Screenshots or videos
=====================

These can be added as seperate API calls. There are limits in the marketplace
for what screenshots and videos can be accepted. There is a 5MB limit on file
uploads.

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

Other APIs
----------

These APIs are not directly about updating Apps. They do not require any
authentication.

Categories
==========

No authentication required.

To find a list of categories available on the marketplace::

        GET /api/apps/category/

Returns the list of categories::

        {"meta":
            {"limit": 20, "next": null, "offset": 0,
             "previous": null, "total_count": 1},
         "objects":
            [{"id": 1, "name": "Webapp",
              "resource_uri": "/api/apps/category/1/"}]
        }

Use the `id` of the category in your app updating.

Search
======

No authentication required.

To find a list of apps in a category on the marketplace::

        GET /api/apps/search/

Returns a list of the apps sorted by relevance::

        {"meta": {},
         "objects":
            [{"absolute_url": "http://../app/marble-run-1/",
              "premium_type": 3, "slug": "marble-run-1", id="26",
              "icon_url": "http://../addon_icons/0/26-32.png",
              "resource_uri": null
             }
         ...

Arguments:

* `cat` (optional): use the category API to find the ids of the categories
* `sort` (optional): one of 'downloads', 'rating', 'price', 'created'

Example, to specify a category sorted by rating::

        GET /api/apps/search/?cat=1&sort=rating

.. _`MDN`: https://developer.mozilla.org
.. _`Marketplace representative`: marketplace-team@mozilla.org
.. _`django-tastypie`: https://github.com/toastdriven/django-tastypie
.. _`APIs for Add-ons`: https://developer.mozilla.org/en/addons.mozilla.org_%28AMO%29_API_Developers%27_Guide
.. _`example marketplace client`: https://github.com/mozilla/Marketplace.Python
