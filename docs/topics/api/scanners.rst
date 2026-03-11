============
Scanners
============

.. note::

    These APIs are subject to change at any time and are for internal use only.


---------------------
Post - Push results
---------------------

.. _scanner-result-push:

This endpoint allows a scanner to push results for an existing version.

    .. note::
        Requires JWT authentication using the service account credentials
        associated with the scanner webhook.

.. http:post:: /api/v5/scanner/results/

    :<json integer version_id: The primary key of the add-on version.
    :<json object results: The scanner results.
    :statuscode 201: Result created successfully.
    :statuscode 400: Invalid payload.
    :statuscode 403: Authentication failed or the authenticated user is not
        the service account of an active webhook with a push event.


----------------------
Patch - Update results
----------------------

.. _scanner-result-patch:

This endpoint allows to update scanner results.

    .. note::
        Requires JWT authentication using the service account credentials
        associated with the scanner webhook.

.. http:patch:: /api/v5/scanner/results/(int:pk)/

    :query string id: The scanner result ID.
    :<json object results: The scanner results.
    :statuscode 204: Results successfully updated.
    :statuscode 400: Invalid payload.
    :statuscode 409: Scanner results already recorded.
