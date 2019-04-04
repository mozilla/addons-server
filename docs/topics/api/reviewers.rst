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


-------------
List Versions
-------------

This endpoint allows you to list versions that can be used either for :ref:`browsing <reviewers-versions-browse>` or diffing versions.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

If the user doesn't have ``AddonsReviewUnlisted`` permissions only listed versions are shown. Otherwise it can contain mixed listed and unlisted versions.

.. http:get:: /api/v4/reviewers/addon/(int:addon_id)/versions/

    :>json int id: The version id.
    :>json string channel: The version channel, which determines its visibility on the site. Can be either ``unlisted`` or ``listed``.
    :>json string version: The version number string for the version.

.. _reviewers-versions-browse:

------
Browse
------

This endpoint allows you to browse through the contents of an Add-on version.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

.. http:get:: /api/v4/reviewers/addon/(int:addon_id)/versions/(int:version_id)/

    Inherits most properties from :ref:`version detail <version-detail-object>` except ``files``.

    .. _reviewers-versions-browse-detail:

    :param file: The specific file in the XPI to retrieve. Defaults to manifest.json, install.rdf or package.json for Add-ons as well as the XML file for search engines.
    :>json string validation_url_json: The absolute url to the addons-linter validation report, rendered as JSON.
    :>json string validation_url: The absolute url to the addons-linter validation report, rendered as HTML.
    :>json boolean has_been_validated: ``True`` if the version has been validated through addons-linter.
    :>json object addon: A simplified :ref:`add-on <addon-detail-object>` object that contains only a few properties: ``id``, ``name``, ``icon_url`` and ``slug``.
    :>json object file: The file attached to this version. See :ref:`version detail -> files[] <version-detail-object>` for more details.
    :>json string file.content: Raw content of the requested file.
    :>json string file.selected_file: The selected file, either from the ``file`` parameter or the default (manifest.json, install.rdf or package.json for Add-ons as well as the XML file for search engines).
    :>json string|null file.download_url: The download url of the selected file or ``null`` in case of a directory.
    :>json array file.entries[]: The complete file-tree of the extracted XPI.
    :>json int file.entries[].depth: Level of folder-tree depth, starting with 0.
    :>json string file.entries[].filename: The filename of the file.
    :>json string file.entries[].path: The absolute path (from the root of the XPI) of the file.
    :>json string file.entries[].sha256: SHA256 hash.
    :>json string file.entries[].mimetype: The determined mimetype of the file or ``application/octet-stream`` if none could be determined.
    :>json string files.entries[].mime_category: The mime type category of this file. Can be ``image``, ``directory``, ``text`` or ``binary``.
    :>json int file.entries[].size: The size in bytes.
    :>json string file.entries[].modified: The exact time of the commit, should be equivalent with ``created``.


-------
Compare
-------

This endpoint allows you to compare two Add-on versions with each other.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

.. http:get:: /api/v4/reviewers/addon/(int:addon_id)/versions/(int:version_id)/compare_to/(int:version_id)/

    Inherits most properties from :ref:`browse detail <reviewers-versions-browse-detail>` except ``file.content`` which is being
    replaced by ``file.diff``.

    Given the complexity of the format, let's see the inline comments.

    The following output represents this git diff.

    .. code:: diff

        diff --git a/README.md b/README.md
        index a37979d..b12683c 100644
        --- a/README.md
        +++ b/README.md
        @@ -1 +1 @@
        -# beastify
        +Updated readme
        diff --git a/manifest.json b/manifest.json
        index aba695f..24f385f 100644
        --- a/manifest.json
        +++ b/manifest.json
        @@ -1,36 +1 @@
        -{
        -
        -  "manifest_version": 2,
        -  "name": "Beastify",
        -  "version": "1.0",
        -
        -  "permissions": [
        -    "http://*/*",
        -    "https://*/*",
        -    "bookmarks",
        -    "made up permission",
        -    "https://google.com/"
        -  ],
        -
        -  "content_scripts": [
        -  {
        -    "matches": ["*://*.mozilla.org/*"],
        -    "js": ["borderify.js"]
        -  },
        -  {
        -    "matches": ["*://*.mozilla.com/*", "https://*.mozillians.org/*"],
        -    "js": ["borderify.js"]
        -  }
        -  ],
        -
        -  "browser_action": {
        -    "default_icon": "button/beasts.png",
        -    "default_title": "Beastify",
        -    "default_popup": "popup/choose_beast.html"
        -  },
        -
        -  "web_accessible_resources": [
        -    "beasts/*.jpg"
        -  ]
        -
        -}
        +{"id": "random"}

    .. code:: javascript

        "diff": [
            {
                "path": "README.md",
                "old_path": "README.md",
                "size": 15,  // Size in bytes
                "lines_added": 1,  // How many lines got added
                "lines_deleted": 1,  // How many lines got deleted
                "is_binary": false,  // Is this a binary file (as determined by git)
                "mode": "M",  // Status of this file, see https://git-scm.com/docs/git-status#_short_format
                "hunks": [
                    {
                        "header": "@@ -1 +1 @@\\n",
                        "old_start": 1,
                        "new_start": 1,
                        "old_lines": 1,
                        "new_lines": 1,
                        "changes": [
                            {
                                "content": "# beastify\\n",
                                "type": "delete",
                                "old_line_number": 1,
                                "new_line_number": -1
                            },
                            {
                                "content": "Updated readme\\n",
                                "type": "insert",
                                "old_line_number": -1,
                                "new_line_number": 1
                            }
                        ]
                    }
                ],
                "parent": "075c5755198be472522477a1b396951b3b68ac18",
                "hash": "00161dcf22afb7bab23cf205f0c903eb5aad5431"
            }
        ]


--------
Download
--------

This endpoint allows you to download files from an Add-on.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

.. http:get:: /api/v4/reviewers/addon/(int:addon_id)/versions/(int:version_id)/download/(str:filename)/

    This will return a streaming response serving the file.

    ``Content-Type``, ``Content-Disposition`` and ``Content-Length`` are correctly set.
