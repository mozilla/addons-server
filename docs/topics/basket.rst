Basket Synchronisation
======================

This documents what data we synchronize with `Basket <https://basket.readthedocs.io/>`_  and how.

Triggers
--------

Every time a field that we're meant to synchronize on an object changes, a full sync of the
object is triggered.

A consequence of this is, since the relation between an addon and an user is part of the add-on
object, when a new user is added as an author, or an existing author is removed from an add-on,
that triggers a full sync of the add-on, including user account information for all its authors.

Objects
-------

We're synchronizing 2 types of objects:

    - User Accounts
    - Add-ons


User Accounts
~~~~~~~~~~~~~

.. note::
     Newsletter opt-in information is not stored by AMO, and therefore not synchronized with the
     rest. It's sent to basket separately directly whenever it changes, through basket's
     `Newsletter API <https://basket.readthedocs.io/newsletter_api.html>`_ ``subscribe`` and
     ``unsubscribe`` endpoints.

.. http:post:: https://basket.mozilla.org/amo-sync/userprofile/

    :<json int id: The numeric user id.
    :<json boolean deleted: Is the account deleted.
    :<json string|null display_name: The name chosen by the user.
    :<json string email: Email address used by the user to login and create this account.
    :<json string|null last_login: The date of the last successful log in to the website.
    :<json string|null location: The location of the user.
    :<json string|null homepage: The user's website.

Add-ons
~~~~~~~

.. http:post:: https://basket.mozilla.org/amo-sync/addon/

    :<json int id: The add-on id on AMO.
    :<json array authors: Array holding information about the authors for the add-on.
    :<json string guid: The add-on `extension identifier <https://developer.mozilla.org/en-US/Add-ons/Install_Manifests#id>`_.
    :<json string name: The add-on name (in add-on's default locale)
    :<json string default_locale: The add-on default locale for translations.
    :<json string slug: The add-on slug.
    :<json string type: The :ref:`add-on type <addon-detail-type>`.
    :<json string status: The :ref:`add-on status <addon-detail-status>`.
    :<json boolean is_disabled: Whether the add-on is disabled or not.
    :<json object|null latest_unlisted_version: Object holding the latest unlisted :ref:`version <version-detail-object>` of the add-on. Only the ``'id``, ``compatibility``, ``is_strict_compatibility_enabled`` and ``version`` fields are present.
    :<json object current_version: Object holding the current :ref:`version <version-detail-object>` of the add-on. Only the ``'id``, ``compatibility``, ``is_strict_compatibility_enabled`` and ``version`` fields are present.
    :<json string last_updated: The date of the last time the add-on was updated by its developer(s).
    :<json object ratings: Object holding ratings summary information about the add-on.
    :<json int ratings.count: The total number of user ratings for the add-on.
    :<json int ratings.text_count: The number of user ratings with review text for the add-on.
    :<json float ratings.average: The average user rating for the add-on.
    :<json float ratings.bayesian_average: The bayesian average user rating for the add-on.
    :<json object categories: Object holding the categories the add-on belongs to.
    :<json array categories[app_name]: Array holding the :ref:`category slugs <category-list>` the add-on belongs to for a given :ref:`add-on application <addon-detail-application>`, referenced by its ``app_name``. (Combine with the add-on ``type`` to determine the name of the category).
    :<json int average_daily_users: The average number of users for the add-on.
    :<json boolean is_recommended: Whether the add-on is recommended by Mozilla or not.

Example data
************

Here is an example of the full json that would be sent for an add-on:

.. code-block:: json

    {
        "authors": [
            {
                "id": 11263,
                "deleted": false,
                "display_name": "serses",
                "email": "mozilla@virgule.net",
                "homepage": "",
                "last_login": "2019-08-06T10:39:44Z",
                "location": ""
            }
        ],
        "average_daily_users": 0,
        "categories": {
            "firefox": [
                "games-entertainment"
            ]
        },
        "current_version": {
            "id": 35900,
            "compatibility": {
                "firefox": {
                    "min": "48.0",
                    "max": "*"
                }
            },
            "is_strict_compatibility_enabled": false,
            "version": "2.0"
        },
        "default_locale": "en-US",
        "guid": "{85ee4a2a-51b6-4f5e-a99c-6d9abcf6782d}",
        "id": 35896,
        "is_disabled": false,
        "is_recommended": false,
        "last_updated": "2019-06-26T11:38:13Z",
        "latest_unlisted_version": {
            "id": 35899,
            "compatibility": {
                "firefox": {
                    "min": "48.0",
                    "max": "*"
                }
            },
            "is_strict_compatibility_enabled": false,
            "version": "1.0"
        },
        "name": "Ibird Jelewt Boartrica",
        "ratings": {
            "average": 4.1,
            "bayesian_average": 4.2,
            "count": 43,
            "text_count": 40
        },
        "slug": "ibird-jelewt-boartrica",
        "status": "nominated",
        "type": "extension"
    }

Here is an example of the full json that would be sent for an user:

.. code-block:: json

    {
        "id": 11263,
        "deleted": false,
        "display_name": "serses",
        "email": "mozilla@virgule.net",
        "homepage": "",
        "last_login": "2019-08-06T10:39:44Z",
        "location": ""
    }
