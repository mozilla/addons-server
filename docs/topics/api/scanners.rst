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

.. http:get:: /api/v4/scanner/results/

    :>json int id: The scanner result ID.
    :>json string scanner: The scanner name.
    :>json string label: Either ``good`` or ``bad``.
    :>json object results: The scanner (raw) results.
