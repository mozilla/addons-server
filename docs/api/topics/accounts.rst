.. _accounts:

========
Accounts
========

User accounts on the Firefox Marketplace.

Account
=======

.. note:: Requires authentication.

The account API, makes use of the term ``mine``. This is an explicit variable to
lookup the logged in user account id.

.. http:get:: /api/v1/account/settings/mine/

    Returns data on the currently logged in user.

    **Response**

    .. code-block:: json

        {
            "resource_uri": "/api/v1/account/settings/1/",
            "display_name": "Nice person",
        }

To update account information:

.. http:patch:: /api/v1/account/settings/mine/

    **Request**

    :param display_name: the displayed name for this user.

    **Response**

    No content is returned in the response.

    :status 201: successfully completed.

Fields that can be updated:

* *display_name*

.. http:get:: /api/v1/account/installed/mine/

    Returns a list of the installed apps for the currently logged in user. This
    ignores any reviewer or developer installed apps.

    **Request**

    The standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.
    :status 200: sucessfully completed.

.. _permission-get-label:

.. http:get:: /api/v1/account/permissions/mine/

    Returns a mapping of the permissions for the currently logged in user.

    **Response**

    .. code-block:: json

        {
            "permissions": {
                "admin": false,
                "developer": false,
                "localizer": false,
                "lookup": true,
                "reviewer": false
            },
            "resource_uri": "/api/v1/account/permissions/1/"
        }

    :param permissions: permissions and properties for the user account. It
        contains boolean values which describe whether the user has the
        permission described by the key of the field.
    :status 200: sucessfully completed.

Feedback
========

.. http:post:: /api/v1/account/feedback/

    Submit feedback to the Marketplace.

    .. note:: Authentication is optional.

    .. note:: This endpoint is rate-limited at 30 requests per hour per user.

    **Request**

    :param chromeless: (optional) "Yes" or "No", indicating whether the user
                       agent sending the feedback is chromeless.
    :param feedback: (required) the text of the feedback.
    :param from_url: (optional) the URL from which the feedback was sent.
    :param platform: (optional) a description of the platform from which the
                     feedback is being sent.

    .. code-block:: json

        {
            "chromeless": "No",
            "feedback": "Here's what I really think.",
            "platform": "Desktop",
            "from_url": "/feedback",
            "sprout": "potato"
        }

    This form uses `PotatoCaptcha`, so there must be a field named `sprout` with
    the value `potato` and cannot be a field named `tuber` with a truthy value.

    **Response**

    .. code-block:: json

        {
            "chromeless": "No",
            "feedback": "Here's what I really think.",
            "from_url": "/feedback",
            "platform": "Desktop",
            "user": null,
        }

    :status 201: successfully completed.
    :status 429: exceeded rate limit.

Newsletter signup
=================

This resource requests that the current user be subscribed to the
Marketplace newsletter.

.. http:post:: /api/v1/account/newsletter/

   **Request**

   :param email: The email address to send newsletters to.

   **Response**

   :status 204: Successfully signed up.
