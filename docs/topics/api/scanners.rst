============
Scanners
============

.. note::

    These APIs are subject to change at any time and are for internal use only.


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
