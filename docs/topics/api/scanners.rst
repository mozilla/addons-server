============
Scanners
============

.. note::

    These APIs are subject to change at any time and are for internal use only.


--------------------
List scanner results
--------------------

.. _scanner-results:

This endpoint returns a list of labelled scanner results.

    .. note::
        Requires authentication and the current user to have read access to the
        scanner results.

.. http:get:: /api/v5/scanner/results/

    :query string label: Filter by label.
    :query string scanner: Filter by scanner name.
    :>json int id: The scanner result ID.
    :>json string scanner: The scanner name.
    :>json string label: Either ``good`` or ``bad``.
    :>json object results: The scanner (raw) results.
    :>json string created: The date the result was created, formatted with `this format <http://ecma-international.org/ecma-262/5.1/#sec-15.9.1.15>`_.
    :>json string|null model_version: The model version when applicable, ``null`` otherwise.


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
