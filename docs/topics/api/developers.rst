==========
Developers
==========

.. note::

    These APIs are subject to change at any time and are for internal use only.

--------
Support
--------

.. _developer-support:

This endpoint allows users to submit a support ticket to AMO. Echoes the submitted data on success.

.. http:post:: /api/v5/developers/support

    :>json string summary: Issue summary.
    :>json string body: Details about the issue.
    :>json string category: Issue category. Can be `policy`, `technical`, or `other`.
