========
Accounts
========

.. note:: This API requires :doc:`authentication <auth>`.

The following API endpoints cover a users account.

.. _`profile`:

-------
Profile
-------

Returns information about your profile.

.. http:get:: /api/v3/accounts/profile/

    **Request:**

    .. sourcecode:: bash

        curl "https://addons.mozilla.org/api/v3/accounts/profile/"
            -H "Authorization: JWT <jwt-token>"

    **Response:**

    .. sourcecode:: json

        {
            "username": "bob",
            "display_name": "bob",
            "email": "a@m.o",
            "bio": "Some biography",
            "deleted": false,
            "display_collections": false,
            "display_collections_fav": false,
            "homepage": "https://a.m.o",
            "location": "Vancouver",
            "notes": null,
            "occupation": "",
            "picture_type": "",
            "picture_url": "/static/img/anon_user.png",
            "read_dev_agreement": "2015-11-20T18:36:12",
            "is_verified": true,
            "region": null,
            "lang": "en-US"
        }

    :statuscode 200: profile found.
    :statuscode 400: an error occurred, check the `error` value in the JSON.
    :statuscode 401: authentication failed.

--------------
Super-creation
--------------

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
