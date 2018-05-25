========
Activity
========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.


-----------------
Review Notes List
-----------------

.. _review-notes-version-list:

This endpoint allows you to list the approval/rejection review history for a version of an add-on.

.. http:get:: /api/v4/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id)/reviewnotes/

    .. note::
        All add-ons require authentication and either
        reviewer permissions or a user account listed as a developer of the
        add-on.

    :>json int count: The number of versions for this add-on.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`per version review notes<review-notes-version-detail-object>`.


-------------------
Review Notes Detail
-------------------

.. _review-notes-version-detail:

This endpoint allows you to fetch a single review note for a specific version of an add-on.

.. http:get:: /api/v4/addons/addon/(int:addon_id|string:addon_slug|string:addon_guid)/versions/(int:id)/reviewnotes/(int:id)/

    .. _review-notes-version-detail-object:

    :>json int id: The id for a review note.
    :>json string action: The :ref:`type of review note<review-note-action>`.
    :>json string action_label: The text label of the action.
    :>json int user.id: The id of the reviewer or author who left the review note.
    :>json string user.name: The name of the reviewer or author.
    :>json string user.url: The link to the profile page for of the reviewer or author.
    :>json string user.username: The username of the reviewer or author.
    :>json string comments: The text content of the review note.
    :>json string date: The date the review note was created.


.. _review-note-action:

    Possible values for the ``action`` field:

    ==========================  ==========================================================
                         Value  Description
    ==========================  ==========================================================
                      approved  Version, or file in the version, was approved
                      rejected  Version, or file in the version, was rejected
              review-requested  Developer requested review
    more-information-requested  Reviewer requested more information from developer
        super-review-requested  Add-on was referred to an admin for attention
                       comment  Reviewer added comment for other reviewers
                   review-note  Generic review comment
    ==========================  ==========================================================


-----------------------
Incoming Mail End-point
-----------------------

.. _activity_mail:

This endpoint allows a mail server or similar to submit a json object containing single email into AMO which will be processed.
The only type of email currently supported is a reply to an activity email (e.g an add-on review, or a reply to an add-on review).
Any other content or invalid emails will be discarded.

.. http:post:: /api/v4/activity/mail

    .. note::
        This API endpoint uses a custom authentication method.
        The value `SecretKey` in the submitted json must match one defined in `settings.INBOUND_EMAIL_SECRET_KEY`.
        The IP address of the request must match one defined in `settings.ALLOWED_CLIENTS_EMAIL_API`, if defined.

    :<json string SecretKey: A value that matches `settings.INBOUND_EMAIL_SECRET_KEY`.
    :<json string Message.TextBody: The plain text body of the email.
    :<json array To: Array of To email addresses.  All will be parsed, and the first matching the correct format used.
    :<json string To[].EmailAddress: An email address in the format `reviewreply+randomuuidstring@addons.mozilla.org`.
