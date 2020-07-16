============
Scanners
============

.. note::

    These APIs are subject to change at any time and are for internal use only.


---------------------
Scanner Results
---------------------

.. _scanner-results:

This endpoint returns a list of labelled scanner results.

    .. note::
        Requires authentication and the current user to have read access to the
        scanner results.

.. http:get:: /api/v4/scanner/results/

    :query string label: Filter by label.
    :query string scanner: Filter by scanner name.
    :>json int id: The scanner result ID.
    :>json string scanner: The scanner name.
    :>json string label: Either ``good`` or ``bad``.
    :>json object results: The scanner (raw) results.
    :>json string created: The date the result was created, formatted with `this format <http://ecma-international.org/ecma-262/5.1/#sec-15.9.1.15>`_.
    :>json string|null model_version: The model version when applicable, ``null`` otherwise.
