========
Accounts
========

The following API endpoints cover a users account.


-------
Account
-------

.. _`account`:

This endpoint returns information about a user's account, by the account id.
Most of the information is optional and provided by the user so may be missing or inaccurate.

.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/

    .. _account-object:

    :>json int id: The numeric user id.
    :>json string username: username chosen by the user, used in the account url. If not set will be a randomly generated string.
    :>json string name: The name chosen by the user, or the username if not set.
    :>json float average_addon_rating: The average rating for addons the developer has listed on the website.
    :>json int num_addons_listed: The number of addons the developer has listed on the website.
    :>json string|null biography: More details about the user.
    :>json string created: The date when this user first logged in and created this account.
    :>json string|null homepage: The user's website.
    :>json string|null location: The location of the user.
    :>json string|null occupation: The occupation of the user.
    :>json string picture_url: URL to a photo of the user, or `/static/img/anon_user.png` if not set.
    :>json string|null picture_type: the image type (only 'image/png' is supported) if a user defined photo has been provided, or none if no photo has been provided.
    :>json boolean is_addon_developer: The user has developed and listed add-ons on this website.
    :>json boolean is_artist: The user has developed and listed themes on this website.


If you authenticate and access your own account by specifing your own ``user_id`` the following additional fields are returned.
If you have `Users:Edit` permission you will see these extra fields for all user accounts.

.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/

    .. _account-object-self:

    :>json string email: Email address used by the user to login and create this account.
    :>json string|null display_name: The name chosen by the user.
    :>json boolean is_verified: The user has been verified via FirefoxAccounts.
    :>json boolean read_dev_agreement: The user has read, and agreed to, the developer agreement that is required to submit addons.
    :>json boolean deleted: Is the account deleted.
    :>json string last_login: The date of the last successful log in to the website.
    :>json string last_login_ip: The IP address of the last successfull log in to the website.


    :statuscode 200: account found.
    :statuscode 400: an error occurred, check the ``error`` value in the JSON.
    :statuscode 404: no account with that user id.


.. important::

    * ``Biography`` can contain HTML, or other unsanitized content, and it is the
      responsibiliy of the client to clean and escape it appropriately before display.


-------
Profile
-------

.. _`profile`:

.. note:: This API requires :doc:`authentication <auth>`.

This endpoint is a shortcut to your own account. It returns an :ref:`account object <account-object-self>`

.. http:get:: /api/v3/accounts/profile/


----
Edit
----

.. _`account-edit`:

.. note::
    This API requires :doc:`authentication <auth>` and `Users:Edit`
    permission to edit accounts other than your own.

This endpoint allows some of the details for an account to be updated.  Any fields
in the :ref:`account <account-object>` (or :ref:`self <account-object-self>`)
but not listed below are not editable and will be ignored in the patch request.

.. http:patch:: /api/v3/accounts/account/(int:user_id|string:username)/

    .. _account-edit-request:

    :<json string|null biography: More details about the user.  No links are allowed.
    :<json string|null display_name: The name chosen by the user.
    :<json string|null homepage: The user's website.
    :<json string|null location: The location of the user.
    :<json string|null occupation: The occupation of the user.
    :<json string|null username: username to be used in the account url.  The username can only contain letters, numbers, underscores or hyphens. All-number usernames are prohibited as they conflict with user-ids.


-------------------
Uploading a picture
-------------------

To upload a picture for the profile the request must be sent as content-type `multipart/form-data` instead of JSON.
Images must be either PNG or JPG; the maximum file size is 4MB.
Other :ref:`editable values <account-edit-request>` can be set at the same time.

.. http:patch:: /api/v3/accounts/account/(int:user_id|string:username)/

    **Request:**

    .. sourcecode:: bash

        curl "https://addons.mozilla.org/api/v3/accounts/account/12345/"
            -g -XPATCH --form "picture_upload=@photo.png"
            -H "Authorization: Bearer <token>"

    :param user-id: The numeric user id.
    :form picture_upload: The user's picture to upload.
    :reqheader Content-Type: multipart/form-data


--------------------
Deleting the picture
--------------------

To delete the account profile picture call the special endpoint.

.. http:delete:: /api/v3/accounts/account/(int:user_id|string:username)/picture


------
Delete
------

.. _`account-delete`:

.. note::
    This API requires :doc:`authentication <auth>` and `Users:Edit`
    permission to delete accounts other than your own.

.. note::
    Accounts of users who are authors of Add-ons can't be deleted.
    All Add-ons (and Themes) must be deleted or transfered to other users first.

This endpoint allows the account to be deleted. The reviews and ratings
created by the user will not be deleted; but all the user's details are
cleared.

.. http:delete:: /api/v3/accounts/account/(int:user_id|string:username)/


------------------
Notifications List
------------------

.. _notification-list:

.. note::
    This API requires :doc:`authentication <auth>` and `Users:Edit`
    permission to list notifications on accounts other than your own.

This endpoint allows you to list the account notifications set for the specified user.
The result is an unpaginated list of the fields below. There are currently 11 notification types.

.. http:get:: /api/v3/accounts/account/(int:user_id|string:username)/notifications/

    :>json string name: The notification short name.
    :>json boolean enabled: If the notification is enabled (defaults to True).
    :>json boolean mandatory: If the notification can be set by the user.


--------------------
Notifications Update
--------------------

.. _`notification-update`:

.. note::
    This API requires :doc:`authentication <auth>` and `Users:Edit`
    permission to set notification preferences on accounts other than your own.

This endpoint allows account notifications to be set or updated. The request should be a dict of `name`:True|False pairs.
Any number of notifications can be changed; only non-mandatory notifications can be changed - attempting to set a mandatory notification will return an error.

.. http:post:: /api/v3/accounts/account/(int:user_id|string:username)/notifications/

    .. _notification-update-request:

    :<json boolean <name>: Is the notification enabled?


--------------
Super-creation
--------------

.. note:: This API requires :doc:`authentication <auth>`.


This allows you to generate a new user account and sign in as that user.

.. important::

    * Your API user must be in the ``Accounts:SuperCreate`` group to access
      this endpoint. Use ``manage.py createsuperuser --add-to-supercreate-group``
      to create a superuser with proper access.
    * This endpoint is not available in all
      :ref:`API environments <api-environments>`.

.. http:post:: /api/v3/accounts/super-create/

    **Request:**

    :param email: assign the user a specific email address.
        A fake email will be assigned by default.
    :param username: assign the user a specific username.
        A random username will be assigned by default.
    :param fxa_id:
        assign the user a Firefox Accounts ID, like one
        returned in the ``uuid`` parameter of a
        `profile request <https://github.com/mozilla/fxa-profile-server/blob/master/docs/API.md#get-v1profile>`_.
        This is empty by default, meaning the user's account will
        need to be migrated to a Firefox Account.
    :param group:
        assign the user to a permission group. Valid choices:

        - **reviewer**: can access add-on reviewer pages, formerly known as Editor Tools
        - **admin**: can access any protected page


    .. sourcecode:: bash

        curl "https://addons.mozilla.org/api/v3/accounts/super-create/" \
            -X POST -H "Authorization: JWT <jwt-token>"

    **Response:**

    .. sourcecode:: json

        {
            "username": "super-created-7ee304ce",
            "display_name": "Super Created 7ee304ce",
            "user_id": 10985,
            "email": "super-created-7ee304ce@addons.mozilla.org",
            "fxa_id": null,
            "groups": [],
            "session_cookie": {
                "encoded": "sessionid=.eJyrVopPLC3JiC8tTi2KT...",
                "name": "sessionid",
                "value": ".eJyrVopPLC3JiC8tTi2KT..."
            }
        }

    :statuscode 201: Account created.
    :statuscode 422: Incorrect request parameters.

    The session cookie will enable you to sign in for a limited time
    as this new user. You can pass it to any login-protected view like
    this:

    .. sourcecode:: bash

        curl --cookie sessionid=... -s -D - \
            "https://addons.mozilla.org/en-US/developers/addon/submit/1" \
            -o /dev/null

.. _`session`:

-------
Session
-------

Log out of the current session. This is for use with the
:ref:`internal authentication <api-auth-internal>` that authenticates browser
sessions.

.. http:delete:: /api/v3/accounts/session/

    **Request:**

    .. sourcecode:: bash

        curl "https://addons.mozilla.org/api/v3/accounts/session/"
            -H "Authorization: Bearer <jwt-token>" -X DELETE

    **Response:**

    .. sourcecode:: json

        {
            "ok": true
        }

    :statuscode 200: session logged out.
    :statuscode 401: authentication failed.
