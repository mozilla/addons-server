=======
Signing
=======

.. note:: This API requires :doc:`authentication <auth>`.

The following API endpoints help you get your add-on signed by Mozilla
so it can be installed into Firefox without error. See
`extension signing <https://wiki.mozilla.org/Addons/Extension_Signing>`_
for more details about Firefox's signing policy.

----------------
Client Libraries
----------------

If you are developing an add-on using the
`Add-on SDK <https://developer.mozilla.org/en-US/Add-ons/SDK>`_,
you may wish to use the
`jpm sign <https://developer.mozilla.org/en-US/Add-ons/SDK/Tools/jpm#jpm_sign>`_
command to interact with the signing API.

If you are using ``curl`` to interact with the API you should be sure to pass
the ``-g`` flag to skip "URL globbing" which won't interact well with add-on
Ids that have {} characters in them.

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

.. http:put:: /api/v3/addons/[string:add-on-id]/versions/[string:version]/

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/addons/@my-addon/versions/1.0/
            -g -XPUT --form 'upload=@build/my-addon.xpi'
            -H 'Authorization: JWT <jwt-token>'

    :param addon-id the id for the add-on.
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

.. _`version-status`:

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

.. http:get:: /api/v3/addons/[string:add-on-id]/versions/[string:version]/(uploads/[string:upload-pk]/)

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/addons/@my-addon/versions/1.0/
            -g -H 'Authorization: JWT <jwt-token>'

    :param addon-id the id for the add-on.
    :param version: the version of the add-on.
    :param upload-pk: (optional) the pk for a specific upload.

    **Response:**

    .. code-block:: json

            {
                "active": true,
                "files": [
                    {
                        "download_url": "https://addons.mozilla.org/api/v3/downloads/file/100/example-id.0-fx+an.xpi?src=api",
                        "hash": "sha256:1bb945266bf370170a656350d9b640cbcaf70e671cf753c410e604219cdd9267",
                        "signed": true
                    }
                ],
                "passed_review": true,
                "pk": "f68abbb3b1624c098fe979a409fe3ce9",
                "processed": true,
                "reviewed": true,
                "url": "https://addons.mozilla.org/api/v3/addons/@example-id.0/uploads/f68abbb3b1624c098fe979a409fe3ce9/",
                "valid": true,
                "validation_results": {},
                "validation_url": "https://addons.mozilla.org/en-US/developers/upload/f68abbb3b1624c098fe979a409fe3ce9",
                "version": "1.0"
            }

    :>json active: version is active.
    :>json files[].download_url:
        URL to :ref:`download the add-on file <download-signed-file>`.
    :>json files[].hash:
        Hash of the file contents, prefixed by the hashing algorithm used.
        Example: ``sha256:1bb945266bf3701...`` . In the case of signed files,
        the hash will be that of the final signed file, not the original
        unsigned file.
    :>json files[].signed: if the file is signed.
    :>json passed_review: if the version has passed review.
    :>json pk: the pk for this upload.
    :>json processed: if the version has been processed by the validator.
    :>json reviewed: if the version has been reviewed.
    :>json url: URL to check the status of this upload.
    :>json valid: if the version passed validation.
    :>json validation_results: the validation results (removed from the example for brevity).
    :>json validation_url: a URL to the validation results in HTML format.
    :>json version: the version.

    :statuscode 200: request successful.
    :statuscode 401: authentication failed.
    :statuscode 403: you do not own this add-on.
    :statuscode 404: add-on or version not found.

.. _download-signed-file:

------------------------
Downloading signed files
------------------------

When checking on your :ref:`request to sign a version <version-status>`,
a successful response will give you an API URL to download the signed files.
This endpoint returns the actual file data for download.

.. http:get:: /api/v3/file/[int:file_id]/[string:base_filename]

    **Request:**

    .. sourcecode:: bash

        curl 'https://addons.mozilla.org/api/v3/file/123/some-addon.xpi?src=api'
            -g -H 'Authorization: JWT <jwt-token>'

    :param file_id: the primary key of the add-on file.
    :param base_filename:
        the base filename. This is just a convenience for
        clients so that they write meaningful file names to disk.

    **Response:**

    There are two possible responses:

    * Binary data containing the file
    * A header that redirects you to a mirror URL for the file.
      In this case, the initial response will include a
      ``SHA-256`` hash of the file in the header ``X-Target-Digest``.
      Clients should check that the final downloaded file matches
      this hash.

    :statuscode 200: request successful.
    :statuscode 302: file resides at a mirror URL
    :statuscode 401: authentication failed.
    :statuscode 404: file does not exist or requester does not have
                     access to it.
