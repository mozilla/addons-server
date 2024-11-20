.. _reviewers:

=========
Reviewers
=========

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.

    The only authentication method available for these APIs is
    :ref:`the internal one<api-auth-internal>`, except for the
    :ref:`validation results<reviewers-validation>` endpoint, which allows both
    internal and :ref:`external auth<api-auth>`.

---------
Subscribe
---------

This endpoint allows you to subscribe the current user to the notification
sent when a new version is submitted on a particular add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.
    .. note::
        ``.../subscribe/`` uses the listed channel implicitly.
        This endpoint is deprecated, use the explicit channel endpoints.

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/subscribe/
.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/subscribe_listed/
.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/subscribe_unlisted/


-----------
Unsubscribe
-----------

This endpoint allows you to unsubscribe the current user to the notification
sent when a new version is submitted on a particular add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.
    .. note::
        ``.../unsubscribe/`` uses the listed channel implicitly.
        This endpoint is deprecated, use the explicit channel endpoints.

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/unsubscribe/
.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/unsubscribe_listed/
.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/unsubscribe_unlisted/


---------------
File Validation
---------------

.. _reviewers-validation:

This endpoint allows you to view the validation results of a given file
belonging to an add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.

.. http:post:: /api/v5/reviewers/addon/(int: addon_id)/file/(int: file_id)/validation/

    :>json object validation: the validation results

-----
Flags
-----

This endpoint allows you to manipulate various reviewer-specific flags on an
add-on.

    .. note::
       Requires authentication and the current user to have ``Reviews:Admin``
       permission.

.. http:patch:: /api/v5/reviewers/addon/(int:addon_id)/flags/

    :>json boolean auto_approval_disabled: Boolean indicating whether auto approval of listed versions is disabled on an add-on or not. When it's ``true``, new listed versions for this add-on will make it appear in the regular reviewer queues instead of being auto-approved.
    :>json boolean auto_approval_disabled_until_next_approval: Boolean indicating whether auto approval of listed versions is disabled on an add-on until the next listed version is approved or not. Has the same effect as ``auto_approval_disabled`` but is automatically reset to ``false`` when the latest listed version of the add-on is manually approved by a human reviewer.
    :>json string|null auto_approval_delayed_until: Date until the add-on auto-approval is delayed for listed versions.
    :>json boolean auto_approval_disabled_unlisted: Boolean indicating whether auto approval of unlisted versions is disabled on an add-on or not. When it's ``true``, new unlisted versions for this add-on will make it appear in the regular reviewer queues instead of being auto-approved.
    :>json boolean auto_approval_disabled_until_next_approval_unlisted: Boolean indicating whether auto approval of unlisted versions is disabled on an add-on until the next unlisted version is approved or not. Has the same effect as ``auto_approval_disabled_unlisted`` but is automatically reset to ``false`` when the latest unlisted version of the add-on is manually approved by a human reviewer.
    :>json string|null auto_approval_delayed_until_unlisted: Date until the add-on auto-approval is delayed for unlisted versions.
    :>json boolean needs_admin_theme_review: Boolean indicating whether the theme needs to be reviewed by an admin or not.

------------------
Allow resubmission
------------------

This endpoint allows you to allow resubmission of an add-on that was previously
denied.

    .. note::
        Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/allow_resubmission/

    :statuscode 202: Success.
    :statuscode 409: The add-on GUID was not previously denied.

-----------------
Deny resubmission
-----------------

This endpoint allows you to deny resubmission of an add-on that was not already
denied.

    .. note::
        Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/deny_resubmission/

    :statuscode 202: Success.
    :statuscode 409: The add-on GUID was already denied.
