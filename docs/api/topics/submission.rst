.. _submission:

==========
Submission
==========

Validate
========

.. note:: The validation does not require you to be authenticated, however you
    cannot create apps from those validations. To validate and submit an app
    you must be authenticated for both steps.

.. _validation-post-label:

.. http:post:: /api/v1/apps/validation/

    **Request**

    :param manifest: URL to the manifest.

    Example:

    .. code-block:: json

        {"manifest": "http://test.app.com/manifest.webapp"}

    Or for a *packaged app*

    :param upload: a dictionary containing the appropriate file data in the upload field.
    :param upload type: the content type.
    :param upload name: the file name.
    :param upload data: the base 64 encoded data.

    Example:

    .. code-block:: json

        {"upload": {"type": "application/foo",
                    "data": "UEsDBAo...gAAAAA=",
                    "name": "mozball.zip"}}

    **Response**

    Returns a :ref:`validation <validation-response-label>` result.

    :status 201: successfully created.

.. _validation-response-label:

.. http:get:: /api/v1/apps/validation/(int:id)/

    **Response**

    Returns a particular validation.

    :param id: the id of the validation.
    :param processed: if the validation has been processed. Hosted apps are
        done immediately but packaged apps are queued. Clients will have to
        poll the results URL until the validation has been processed.
    :param valid: if the validation passed.
    :param validation: the resulting validation messages if it failed.
    :status 200: successfully completed.

    Example not processed:

    .. code-block:: json

        {
            "id": "123",
            "processed": false,
            "resource_uri": "/api/v1/apps/validation/123/",
            "valid": false,
            "validation": ""
        }

    Example processed and passed:

    .. code-block:: json

        {
            "id": "123",
            "processed": true,
            "resource_uri": "/api/v1/apps/validation/123/",
            "valid": true,
            "validation": ""
        }

    Example processed and failed:

    .. code-block:: json

        {
            "id": "123",
            "processed": true,
            "resource_uri": "/api/v1/apps/validation/123/",
            "valid": false,
            "validation": {
            "errors": 1, "messages": [{
                "tier": 1,
                "message": "Your manifest must be served with the HTTP header \"Content-Type: application/x-web-app-manifest+json\". We saw \"text/html; charset=utf-8\".",
                "type": "error"
            }],
        }

How to submit an app
====================

Submitting an app involves a few steps. The client must be logged in for all
these steps and the user submitting the app must have accepted the terms.

1. :ref:`Validate your app <validation-post-label>`. The validation will return
   a valid manifest id or upload id.
2. :ref:`Post your app <app-post-label>` using the valid manifest id or upload
   id. This will create an app and populate the data with the
   contents of the manifest. It will return the current app data.
3. :ref:`Update your app <app-put-label>`. Not everything that the Firefox
   Marketplace needs will be in the app, as the manifest does not
   contain all the data. Update the required fields.
4. :ref:`Create a screenshot <screenshot-post-label>`. For listing on the
   Firefox Marketplace, at least one screenshot is needed.
5. :ref:`Ask for a review <enable-patch-label>`. All apps need to be reviewed,
   this will add it to the review queue.
