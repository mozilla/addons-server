=======
Signing
=======

.. note:: This API requires :doc:`authentication <auth>`.

-------------------
Uploading a version
-------------------

You can upload a new version for signing by issuing a ``PUT`` request
and including the contents of your add-on in the ``upload`` parameter
as multi-part formdata. This will create a pending version on the
add-on and will prevent future submissions to this version unless
validation or review fails.

If the upload succeeded then it will be submitted for
validation and you will be able to check its status.

.. http:put:: /api/v3/addons/[string:add-on-guid]/versions/[string:version]/

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/addons/my-addon/versions/1.0/
            -XPUT --form 'upload=@build/my-addon.xpi' -H 'Authorization: JWT <jwt-token>'

    :param addon-guid: the GUID for the add-on.
    :param version: the version of the add-on.
    :form upload: the add-on being uploaded.
    :reqheader Content-Type: multipart/form-data

    **Response:**

    The response body will be the same as the :ref:`version-status` response.

    :statuscode 201: new add-on and version created.
    :statuscode 202: new version created.
    :statuscode 400: an error occurred, check the `error` value in the JSON.
    :statuscode 401: authentication failed.
    :statuscode 403: you do not own this add-on.
    :statuscode 409: version already exists.

------------------
Creating an add-on
------------------

If this is the first time that your add-on's UUID has been seen then
the add-on will be created as an unlisted add-on when the version is
uploaded.

.. _version-status:

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

.. http:get:: /api/v3/addons/[string:add-on-guid]/versions/[string:version]/

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/addons/my-addon/versions/1.0/
            -H 'Authorization: JWT <jwt-token>'

    :param addon-guid: the GUID for the add-on.
    :param version: the version of the add-on.

    **Response:**

    .. code-block:: json

            {
                "active": true,
                "files": [
                    {
                        "download_url": "https://addons.mozilla.org/firefox/downloads/file/100/unlisted_wat-1.0-fx+an.xpi?src=api",
                        "signed": true
                    }
                ],
                "passed_review": true,
                "processed": true,
                "reviewed": true,
                "url": "https://addons.mozilla.org/api/v3/addons/%40new-unlisted-api/versions/1.0/",
                "valid": true,
                "validation_results": {},
                "validation_url": "https://addons.mozilla.org/en-US/developers/upload/f68abbb3b1624c098fe979a409fe3ce9",
                "version": "1.0"
            }

    :>json active: version is active.
    :>json files.download_url: URL to download the add-on file.
    :>json files.signed: if the file is signed.
    :>json passed_review: if the version has passed review.
    :>json processed: if the version has been processed by the validator.
    :>json reviewed: if the version has been reviewed.
    :>json url: URL to this end point.
    :>json valid: if the version passed validation.
    :>json validation_results: the validation results (removed from the example for brevity).
    :>json validation_url: a URL to the validation results in HTML format.
    :>json version: the version.

    :statuscode 200: request successful.
    :statuscode 401: authentication failed.
    :statuscode 403: you do not own this add-on.
    :statuscode 404: add-on or version not found.
