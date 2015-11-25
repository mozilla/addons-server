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

.. http:get:: /api/v3/account/profile/

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/account/profile/
            -H 'Authorization: JWT <jwt-token>'

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
