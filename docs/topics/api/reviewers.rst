.. _reviewers:

=========
Reviewers
=========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

---------
Subscribe
---------

This endpoint allows you to subscribe the current user to the notification
sent when a new listed version is submitted on a particular add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.

.. http:post::/api/v3/reviewers/addon/(int:addon_id)/subscribe/

-----------
Unsubscribe
-----------

This endpoint allows you to unsubscribe the current user to the notification
sent when a new listed version is submitted on a particular add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.

.. http:post::/api/v3/reviewers/addon/(int:addon_id)/unsubscribe/

-------
Disable
-------

This endpoint allows you to disable the public listing for an add-on.

    .. note::
       Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post::/api/v3/reviewers/addon/(int:addon_id)/disable/

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

.. http:post::/api/v3/reviewers/addon/(int:addon_id)/enable/


---------------------
Disable Auto Approval
---------------------

This endpoint allows you to disable auto-approval for an add-on. When in this
state, new versions for this add-on will make it appear in the regular reviewer
queues instead of being auto-approved.

    .. note::
       Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post::/api/v3/reviewers/addon/(int:addon_id)/disable-auto-approval/

--------------------
Enable Auto Approval
--------------------

This endpoint allows you to re-enable auto-approval for an add-on. Note that it
won't force a non-webextension version to be auto-approved, it still needs to
follow the normal conditions.

    .. note::
        Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post::/api/v3/reviewers/addon/(int:addon_id)/enable-auto-approval/

-----------------------
Clear Admin Review Flag
-----------------------

This endpoint allows you to clear either the code or the content admin review
flag that reviewers can set on an add-on.

    .. note::
        Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post::/api/v3/reviewers/addon/1/clear_admin_review_flag/

    :query string flag_type: The flag to clear. Can be either ``code`` or
        ``content``.
