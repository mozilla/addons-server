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

This endpoint allows you to browse through the contents of an Add-on version.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

.. http:get:: /api/v4/reviewers/browse/(int:version_id)/

    :param file: The specific file in the XPI to retrieve. Defaults to manifest.json, install.rdf or package.json for Add-ons as well as the XML file for search engines.

    :>json int id: The version id.
    :>json string channel: The version channel, which determines its visibility on the site. Can be either ``unlisted`` or ``listed``.
    :>json object compatibility: Object detailing which :ref:`applications <addon-detail-application>` the version is compatible with. See :ref:`version <version-detail-object>` for more details.
    :>json object compatibility[app_name].max: Maximum version of the corresponding app the version is compatible with. Should only be enforced by clients if ``is_strict_compatibility_enabled`` is ``true``.
    :>json object compatibility[app_name].min: Minimum version of the corresponding app the version is compatible with.
    :>json string edit_url: The URL to the developer edit page for the version.
    :>json object license: Object holding information about the license for the version. See :ref:`version <version-detail-object>` for more details.
    :>json string|object|null release_notes: The release notes for this version (See :ref:`translated fields <api-overview-translations>`).
    :>json string reviewed: The date the version was reviewed at.
    :>json boolean is_strict_compatibility_enabled: Whether or not this version has `strictCompatibility <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#strictCompatibility>`_. set.
    :>json string version: The version number string for the version.
    :>json boolean has_been_validated: Has linting results from addons-linter (for WebExtensions) or amo-validator (for legacy Add-ons).
    :>json string validation_url_json: Link to the validation results (JSON object).
    :>json string validation_url: Link to the validation results (HTML page).
    :>json int files[].id: The id for a file.
    :>json string files[].created: The creation date for a file.
    :>json string files[].hash: The hash for a file.
    :>json boolean files[].is_mozilla_signed_extension: Whether the file was signed with a Mozilla internal certificate or not.
    :>json boolean files[].is_restart_required: Whether the file requires a browser restart to work once installed or not.
    :>json boolean files[].is_webextension: Whether the file is a WebExtension or not.
    :>json array files[].permissions[]: Array of the webextension permissions for this File, as strings. Empty for non-webextensions.
    :>json string files[].platform: The :ref:`platform <addon-detail-platform>` for a file.
    :>json int files[].size: The size for a file, in bytes.
    :>json int files[].status: The :ref:`status <addon-detail-status>` for a file.
    :>json string files[].url: The (absolute) URL to download a file. Clients using this API can append an optional ``src`` query parameter to the url which would indicate the source of the request (See :ref:`download sources <download-sources>`).
    :>json string files[].content: Content of the requested file.
    :>json boolean/string files[].entries[].binary: ``True`` if the file is a binary file (e.g an .exe, dll, java, swf file), ``'image'`` if the file is an image or ``False`` otherwise. If ``False`` or ``'image'`` the file should be presentable to the user.
    :>json image files[].entries[].depth: Level of folder-tree depth, starting with 0.
    :>json boolean files[].entries[].is_directory: Wheather the file is a directory.
    :>json string files[].entries[].filename: The filename of the file.
    :>json string files[].entries[].path: The absolute path (from the root of the XPI) of the file.
    :>json string files[].entries[].sha256: SHA256 hash.
    :>json string files[].entries[].mimetype: The determined mimetype of the file or ``application/octet-stream`` if none could be determined.
    :>json int files[].entries[].size: The size in bytes.
    :>json string files[].entries[].binary: is_binary,
    :>json string files[].entries[].modified: The exact time of the commit, should be equivalent with ``created``.
