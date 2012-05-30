.. _api:

======================
Marketplace API
======================

Before you go any further *please note the following*:

* This is currently a document in progress, prior to the API's being written so
  don't expect this to work. Formal API documentation will go on to `MDN`_ when
  it's ready.
* There is a seperate AMO set of APIs. You can find documentation of those on
  `AMO api on MDN`_.

Overall notes
-------------

Authentication
==============

Not all APIs require authentication. Each API will note if it needs
authentication.

Currently only two legged OAuth authentication is supported. This is focused on
clients who would like to create multiple apps on the app store from an end
point.

To get started you will need to get an OAuth token created in the site for you.
For more information on creating an OAuth token, contact the `marketplace
team`_, letting them know which Marketplace user account you would like to use
for authentication. Changing this later will give problems accessing old data.

Once you've got your token, you will need to ensure that the OAuth token is
sent correctly in each request.

*TODO*: insert example and more notes on OAuth.

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

To validate an app::

        POST /en-US/api/apps/validation/

Body data should contain the manifest in JSON::

        {"manifest": "http://test.app.com/manifest"}

Validations are done async on the marketplace. The call will return immediately
with a status of 201::

        {"id": "123",
         "manifest": "http://foo.com",
         "processed": false,
         "resource_uri": "/en-US/api/apps/validation/123/",
         "valid": false,
         "validation": ""}

To see how it's doing, poll for a result using the `resource_uri`::

        GET /en-US/api/apps/validation/123/

This will return the status of the validation. Validation not processed yet::

        {"id": "123",
         "processed": false,
         "resource_uri": "/en-US/api/apps/validation/123/",
         "valid": false,
         "validation": ""}

Validation processed and good::

        {"id": "123",
         "processed": true,
         "resource_uri": "/en-US/api/apps/validation/123/",
         "valid": true,
         "validation": ""}

Validation processed and an error::

        {"id": "123",
         "processed": true,
         "resource_uri": "/en-US/api/apps/validation/123/",
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

This API requires authentication and a successfully validated manifest. To
create an app with your validated manifest::

        POST /en-US/api/apps/app/

Body data should contain the manifest id from the validate call and other data
in JSON::

        {"manifest_id": "123"}

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
         "resource_uri": "/en-US/api/apps/app/1/",
         "slug": "mozillaball",
         "status": 0,
         "summary": "Exciting Open Web development action!",
         "support_email": null,
         "support_url": null
        }

Fields:

* manifest_id (required): the id of the manifest returned from verfication.

Update
======

This API requires authentication and a successfully created app::

        PUT /en-US/api/apps/app/<app id>/

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
  'desktop', 'phone', 'tablet'.
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

Status
======

This API requires authentication and a successfully created app.

To view details of an app, including its review status::

        GET /en-US/api/apps/app/<app id>/

Returns the status of the app::

        {"slug": "your-test-app",
         "name": "My cool app",
         ...}

Delete
======

This API requires authentication and a successfully created app.

Deletes an app::

        DELETE /en-US/api/apps/app/<app id>/

The app will only be hard deleted if it is incomplete. Otherwise it will be
soft deleted. A soft deleted app will not appear publicly in any listings
pages, but it will remain so that receipts, purchasing and other components
work.

*TODO*: implement this.

Screenshots or videos
=====================

These can be added as seperate API calls. There are limits in the marketplace
for what screenshots and videos can be accepted. There is a 5MB limit on file
uploads.

Create
++++++

Create a screenshot or video::

        PUT /en-US/api/apps/preview/?app=<app id>

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
         "resource_uri": "/en-US/api/apps/preview/1/"}

Get
+++

Get information about the screenshot or video::


        GET /en-US/api/apps/preview/<preview id>/

Returns::

        {"addon": "/en-US/api/apps/app/1/", "id": 1, "position": 1,
         "thumbnail_url": "/img/uploads/...", "image_url": "/img/uploads/...",
         "filetype": "image/png", "resource_uri": "/en-US/api/apps/preview/1/"}


Delete
++++++

Delete a screenshot of video::

        DELETE /en-US/api/apps/previe/<preview id>/

This will return a 204 if the screenshot has been deleted.


Other APIs
----------

These APIs are not directly about updating Apps. They do not require any
authentication.

Categories
==========

No authentication required.

To find a list of categories available on the marketplace::

        GET /en-US/api/apps/categories/

Returns the list of categories::

        {"meta":
            {"limit": 20, "next": null, "offset": 0,
             "previous": null, "total_count": 1},
         "objects":
            [{"id": 1, "name": "Webapp",
              "resource_uri": "/en-US/api/apps/category/1/"}]
        }

Use the `id` of the category in your app updating.

Search
======

No authentication required.

To find a list of apps in a category on the marketplace::

        GET /en-US/api/apps/search/

Returns a list of the apps sorted by relevance::

        {"meta": {},
         "objects":
            [{"absolute_url": "http://../en-US/app/marble-run-1/",
              "premium_type": 3, "slug": "marble-run-1", id="26",
              "icon_url": "http://../addon_icons/0/26-32.png",
              "resource_uri": null
             }
         ...

Arguments:

* `cat` (optional): use the category API to find the ids of the categories
* `sort` (optional): one of 'downloads', 'rating', 'price', 'created'

Example, to specify a category sorted by rating::

        GET /en-US/api/apps/search/?cat=1&sort=rating

Sorting options:

.. _`MDN`: https://developer.mozilla.org
.. _`marketplace team`: marketplace-team@mozilla.org
.. _`django-tastypie`: https://github.com/toastdriven/django-tastypie
.. _`AMO api on MDN`: https://developer.mozilla.org/en/addons.mozilla.org_%28AMO%29_API_Developers%27_Guide
