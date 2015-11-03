=======
Signing
=======

This API requires :doc:`authentication <auth>`.

-------------------
Uploading a version
-------------------

You can upload a new version for signing by issuing a ``PUT`` request
and including the contents of your add-on in the ``upload`` parameter
as multi-part formdata. This will create a pending version on the
add-on and will prevent future submissions to this version unless
validation or review fails.

Example::

    curl https://addons.mozilla.org/en-US/firefox/api/v3/addons/my-addon/versions/1.0/
         -XPUT --form 'upload=@build/my-addon.xpi' -H 'Authorization: JWT <jwt-token>'

The response will be the same as the :ref:`check-status` response.

If your upload has the right metadata then it will be submitted for
validation and you will be able to check its status.

------------------
Creating an add-on
------------------

If this is the first time that your add-on's UUID has been seen then
the add-on will be created as an unlisted add-on when the version is
uploaded.

.. _check-status:

-----------------------------------
Checking the status of your upload
-----------------------------------

You can check the status of your upload by issuing a ``GET`` request.
There are a few things that will happen once a version is uploaded
and the status of those events is included in the response.

Once validation is completed (whether it passes or fails) then the
``processed`` property will be ``true``. You can check if validation
passed using the ``valid`` property and check the results with
``validation_results``.

If validation passed then your add-on will be submitted for review.
In the case of unlisted add-ons this will happen automatically if
the add-on passes a strict set of tests. If your add-on is listed
then it will be reviewed by a human and that will take a bit
longer. Once review is complete then the ``reviewed`` property
will be set and you can check the results with the ``passed_review``
property.

To make the request using curl::

    curl https://addons.mozilla.org/en-US/firefox/api/v3/addons/my-addon/versions/1.0/
         -H 'Authorization: JWT <jwt-token>'

Here's a full example of a check status response::

    {
        "active": true,
        "files": [
            {
                "download_url": "https://addons.mozilla.org/firefox/downloads/file/100/unlisted_wat-0.0.0-fx+an.xpi?src=api",
                "signed": true
            }
        ],
        "passed_review": true,
        "processed": true,
        "reviewed": true,
        "url": "https://addons.mozilla.org/en-US/firefox/api/v3/addons/%40new-unlisted-api/versions/0.0.0/",
        "valid": true,
        "validation_results": {
            ... snip ...
        },
        "validation_url": "https://addons.mozilla.org/en-US/developers/upload/f68abbb3b1624c098fe979a409fe3ce9",
        "version": "0.0.0"
    }
