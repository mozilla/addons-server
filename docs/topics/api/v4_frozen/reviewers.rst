.. _v4-reviewers:

=========
Reviewers
=========

.. note::

    These v4 APIs are now frozen.
    See :ref:`the API versions available<api-versions-list>` for details of the
    different API versions available.
    The only authentication method available at
    the moment is :ref:`the internal one<v4-api-auth-internal>`.

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

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/subscribe/
.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/subscribe_listed/
.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/subscribe_unlisted/


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

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/unsubscribe/
.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/unsubscribe_listed/
.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/unsubscribe_unlisted/


-------
Disable
-------

This endpoint allows you to disable the public listing for an add-on.

    .. note::
       Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/disable/

------
Enable
------

This endpoint allows you to re-enable the public listing for an add-on. If the
add-on can't be public because it does not have public versions, it will
instead be changed to awaiting review or incomplete depending on the status
of its versions.

    .. note::
        Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/enable/


-----
Flags
-----

This endpoint allows you to manipulate various reviewer-specific flags on an
add-on.

    .. note::
       Requires authentication and the current user to have ``Reviews:Admin``
       permission.

.. http:patch:: /api/v4/reviewers/addon/(int:addon_id)/flags/

    :>json boolean auto_approval_disabled: Boolean indicating whether auto approval are disabled on an add-on or not. When it's ``true``, new versions for this add-on will make it appear in the regular reviewer queues instead of being auto-approved.
    :>json boolean auto_approval_disabled_until_next_approval: Boolean indicating whether auto approval are disabled on an add-on until the next version is approved or not. Has the same effect as ``auto_approval_disabled`` but is automatically reset to ``false`` when the latest version of the add-on is manually approved by a human reviewer.
    :>json string|null auto_approval_delayed_until: Date until the add-on auto-approval is delayed.
    :>json boolean needs_admin_code_review: Boolean indicating whether the add-on needs its code to be reviewed by an admin or not.
    :>json boolean needs_admin_content_review: Boolean indicating whether the add-on needs its content to be reviewed by an admin or not.
    :>json boolean needs_admin_theme_review: Boolean indicating whether the theme needs to be reviewed by an admin or not.

------------------
Allow resubmission
------------------

This endpoint allows you to allow resubmission of an add-on that was previously
denied.

    .. note::
        Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/allow_resubmission/

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

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/deny_resubmission/

    :statuscode 202: Success.
    :statuscode 409: The add-on GUID was already denied.
