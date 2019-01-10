.. _reviewers:

=========
Reviewers
=========

.. note::

    These APIs are experimental and are currently being worked on. Endpoints
    may change without warning. Consider the :ref:`v3 API<api-stable-v3>`
    if you need stability. The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

---------
Subscribe
---------

This endpoint allows you to subscribe the current user to the notification
sent when a new listed version is submitted on a particular add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/subscribe/

-----------
Unsubscribe
-----------

This endpoint allows you to unsubscribe the current user to the notification
sent when a new listed version is submitted on a particular add-on.

    .. note::
        Requires authentication and the current user to have any
        reviewer-related permission.

.. http:post:: /api/v4/reviewers/addon/(int:addon_id)/unsubscribe/

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
    :>json string|null pending_info_request: Deadline date for the pending info request as a string, or ``null``.
    :>json boolean needs_admin_code_review: Boolean indicating whether the add-on needs its code to be reviewed by an admin or not.
    :>json boolean needs_admin_content_review: Boolean indicating whether the add-on needs its content to be reviewed by an admin or not.


------
Browse
------

This endpoint allows you to browse through the contents of an Add-on versions file.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

.. http:get:: /api/v4/reviewers/browse/(int:file_id)/

    :param file: The specific file in the XPI to retrieve. Defaults to manifest.json, install.rdf or package.json for Add-ons as well as the XML file for search engines.
    :>json int id: The file id.
    :>json string created: The date the file was created.
    :>json string hash: The sha256 hash of the file.
    :>json boolean is_restart_required: Whether the file requires a browser restart to work once installed or not.
    :>json boolean is_webextension: Whether the file is a WebExtension or not.
    :>json boolean is_mozilla_signed_extension: Whether the file was signed with a Mozilla internal certificate or not.
    :>json string platform: The :ref:`platform <addon-detail-platform>` for a file.
    :>json int size: The size of the file, in bytes.
    :>json string status: The :ref:`add-on status <addon-detail-status>`.
    :>json string download_url: The (absolute) url to download the XPI file.
    :>json array permissions[]: Array of the webextension permissions for this File, as strings. Empty for non-webextensions.
    :>json boolean has_been_validated: Has linting results from addons-linter (for WebExtensions) or amo-validator (for legacy Add-ons).
    :>json string validation_url_json: Link to the validation results (JSON object).
    :>json string validation_url: Link to the validation results (HTML page).
    :>json string content: Content of the requested file.
