.. _reviewers:

=========
Reviewers
=========

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.
    The only authentication method available at
    the moment is :ref:`the internal one<api-auth-internal>`.

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


-------
Disable
-------

This endpoint allows you to disable the public listing for an add-on.

    .. note::
       Requires authentication and the current user to have ``Reviews:Admin``
        permission.

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/disable/

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

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/enable/


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

-------------
List Versions
-------------

This endpoint allows you to list versions that can be used either for :ref:`browsing <reviewers-versions-browse>` or diffing versions.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

        This endpoint is not paginated as normal, and instead will return all
        results without obeying regular pagination parameters.


If the user doesn't have ``AddonsReviewUnlisted`` permissions only listed versions are shown. Otherwise it can contain mixed listed and unlisted versions.

.. http:get:: /api/v5/reviewers/addon/(int:addon_id)/versions/

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

.. http:get:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:version_id)/

    Inherits the following properties from :ref:`version detail <version-detail-object>`: ``id``, ``channel``, ``reviewed`` and ``version``.

    .. _reviewers-versions-browse-detail:

    :param string file: The specific file in the XPI to retrieve. Defaults to manifest.json, install.rdf or package.json for Add-ons as well as the XML file for search engines.
    :param boolean file_only: Indicates that the API should only return data for the requested file, and not version data. If this is ``true`` then the only property returned of those listed below is the ``file`` property.
    :>json string validation_url_json: The absolute url to the addons-linter validation report, rendered as JSON.
    :>json string validation_url: The absolute url to the addons-linter validation report, rendered as HTML.
    :>json boolean has_been_validated: ``True`` if the version has been validated through addons-linter.
    :>json object addon: A simplified :ref:`add-on <addon-detail-object>` object that contains only a few properties: ``id``, ``name``, ``icon_url`` and ``slug``.
    :>json array file_entries[]: The complete file-tree of the extracted XPI.
    :>json int file_entries[].depth: Level of folder-tree depth, starting with 0.
    :>json string file_entries[].filename: The filename of the file.
    :>json string file_entries[].path: The absolute path (from the root of the XPI) of the file.
    :>json string file_entries[].mime_category: The mime type category of this file. Can be ``image``, ``directory``, ``text`` or ``binary``.
    :>json object file: The requested file.
    :>json int file.id: The id of the submitted file (i.e., the xpi file).
    :>json string file.content: Raw content of the requested file.
    :>json string file.selected_file: The selected file, either from the ``file`` parameter or the default (manifest.json, install.rdf or package.json for Add-ons as well as the XML file for search engines).
    :>json string|null file.download_url: The download url of the selected file or ``null`` in case of a directory.
    :>json string file.mimetype: The determined mimetype of the selected file or ``application/octet-stream`` if none could be determined.
    :>json string file.sha256: SHA256 hash of the selected file.
    :>json int file.size: The size of the selected file in bytes.
    :>json string file.filename: The filename of the file.
    :>json string file.mime_category: The mime type category of this file. Can be ``image``, ``directory``, ``text`` or ``binary``.
    :>json boolean uses_unknown_minified_code: Indicates that the selected file could be using minified code.


-------
Compare
-------

This endpoint allows you to compare two Add-on versions with each other.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.

.. http:get:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:base_version_id)/compare_to/(int:version_id)/

    .. note::

        Contrary to what ``git diff`` does, this API renders a hunk full of unmodified lines for unmodified files.

    Inherits most properties from :ref:`browse detail <reviewers-versions-browse-detail>`, except that most of the `file.entries[]` properties
    and `file.download_url` can be `null` in case of a deleted file.

    Properties specific to this endpoint:

    :>json array file_entries[]: The complete file-tree of the extracted XPI.
    :>json string file.entries[].status: Status of this file, see https://git-scm.com/docs/git-status#_short_format
    :>json int file_entries[].depth: Level of folder-tree depth, starting with 0.
    :>json string file_entries[].filename: The filename of the file.
    :>json string file_entries[].path: The absolute path (from the root of the XPI) of the file.
    :>json string file_entries[].mime_category: The mime type category of this file. Can be ``image``, ``directory``, ``text`` or ``binary``.
    :>json object|null diff: See the following output with inline comments for a complete description.
    :>json object base_file: The file attached to the base version you're comparing against.
    :>json object base_file.id: The id of the base file.
    :>json boolean uses_unknown_minified_code: Indicates that the selected file in either the current or the parent version could be using minified code.

    Git patch we're talking about:

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


    The following represents the git patch from above.

    .. code:: javascript

        "diff": {
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


-----------------
Drafting Comments
-----------------

These endpoints allow you to draft comments that can be submitted through the regular reviewer pages.

    .. note::
        Requires authentication and the current user to have ``ReviewerTools:View``
        permission for listed add-ons as well as ``Addons:ReviewUnlisted`` for
        unlisted add-ons. Additionally the current user can also be the owner
        of the add-on.


.. http:get:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:version_id)/draft_comments/

    Retrieve existing draft comments for a specific version. See :ref:`pagination <api-overview-pagination>` for more details.

    :>json int count: The number of comments for this version.
    :>json string next: The URL of the next page of results.
    :>json string previous: The URL of the previous page of results.
    :>json array results: An array of :ref:`comments <reviewers-draft-comment-detail-object>`.


.. http:get:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:version_id)/draft_comments/(int:comment_id)/

    .. _reviewers-draft-comment-detail-object:

    :>json int id: The id of the draft comment object.
    :>json string comment: The comment that is being drafted as part of a review. Specific to a line in a file.
    :>json string|null filename: The full file path a specific comment is related to. Can be ``null`` in case a comment doesn't belong to a specific file but the whole version.
    :>json int|null lineno: The line number a specific comment is related to. Please make sure that in case of comments for git diffs, that the `lineno` used here belongs to the file in the version that belongs to `version_id` and not it's parent. Can be ``null`` in case a comment belongs to the whole file and not to a specific line.
    :>json int version_id: The id of the version.
    :>json int user.id: The id for an author.
    :>json string user.name: The name for an author.
    :>json string user.username: The username for an author.
    :>json string|null user.url: The link to the profile page for an author, if the author's profile is public.
    :>json object|null canned_response: Object holding the :ref:`canned response <reviewers-canned-response-format>` if set.

.. http:post:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:version_id)/draft_comments/

    Create a draft comment for a specific version.

    :<json string comment: The comment that is being drafted as part of a review.
    :<json string filename: The full file path this comment is related to. This must represent the full path, including sub-folders and relative to the root. E.g ``lib/scripts/background.js``
    :<json int lineno: The line number this comment is related to (optional). Please make sure that in case of comments for git diffs, that the `lineno` used here belongs to the file in the version that belongs to `version_id` and not it's parent.
    :<json int canned_response: The id of the :ref:`canned response <reviewers-canned-response-format>` (optional).

    :statuscode 201: New comment has been created.
    :statuscode 400: An error occurred, check the `error` value in the JSON.
    :statuscode 403: The user doesn't have the permission to create a comment. This might happen (among other cases) when someone without permissions for unlisted versions tries to add a comment for an unlisted version (which shouldn't happen as the user doesn't see unlisted versions, but it's blocked here too).

    **Response**
        In case of successful creation, the response is a :ref:`draft comment object<reviewers-draft-comment-detail-object>`.

.. http:delete:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:version_id)/draft_comments/(int:comment_id)/

    Delete a draft comment.

    :statuscode 204: The comment has been deleted successfully.
    :statuscode 404: The user doesn't have the permission to delete. This might happen when someone tries to delete a comment created by another reviewer or author.


.. http:patch:: /api/v5/reviewers/addon/(int:addon_id)/versions/(int:version_id)/draft_comments/(int:comment_id)

    Update a comment, it's filename or line number.

    :<json string comment: The comment that is being drafted as part of a review.
    :<json string filename: The full file path this comment is related to. This must represent the full path, including sub-folders and relative to the root. E.g ``lib/scripts/background.js``
    :<json int lineno: The line number this comment is related to. Please make sure that in case of comments for git diffs, that the `lineno` used here belongs to the file in the version that belongs to `version_id` and not it's parent.
    :<json int canned_response: The id of the :ref:`canned response <reviewers-canned-response-format>` (optional).

    :statuscode 200: The comment has been updated.
    :statuscode 400: An error occurred, check the `error` value in the JSON.

    **Response**
        In case of successful creation, the response is a :ref:`draft comment object<reviewers-draft-comment-detail-object>`.


.. _reviewers-canned-response-format:

    Canned response format:

    :>json int id: The canned response id.
    :>json string title: The title of the canned response.
    :>json string response: The text that will be filled in as the response.
    :>json string category: The category of the canned response. For example, "Other", "Privacy reasons" etc.
