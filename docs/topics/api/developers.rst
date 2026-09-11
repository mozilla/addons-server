==========
Developers
==========

.. note::

    These APIs are subject to change at any time and are for internal use only.

---------
Agreement
---------

.. _developer-agreement:

This endpoint allows users to accept the developer agreement.

.. http:post:: /api/v5/developers/agreement

    :<json string display_name: User's chosen display name. Required if the user doesn't have a display name yet. Errors if they already have one.
    :<json string last_developer_agreement_change: The date of the last agreement change.

.. http:get:: /api/v5/developers/agreement

    :>json string|null display_name: The user's display name, if set.
    :>json boolean has_read_developer_agreement: Whether the user has agreed to the latest agreement.
    :>json string last_developer_agreement_change: The date of the last agreement change.

--------
Support
--------

.. _developer-support:

This endpoint allows users to submit a support ticket to AMO. Echoes the submitted data on success.

.. http:post:: /api/v5/developers/support

    :>json string summary: Issue summary.
    :>json string body: Details about the issue.
    :>json string category: Issue category. Can be `policy`, `technical`, or `other`.
