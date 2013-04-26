.. _accounts:

========
Accounts
========

User accounts on the Firefox Marketplace.

Account
=======

The account API, makes use of the term `mine`. This is an explicit variable to
lookup the logged in user account id.

.. http:get:: /api/v1/account/settings/mine/

    Returns data on the currently logged in user.

    .. note:: Requires authentication.

    **Response**

    .. code-block:: json

        {
            "resource_uri": "/api/v1/account/settings/1/",
            "display_name": "Nice person",
        }

The same information is also accessible at the canoncial `resource_uri`
`/api/v1/account/settings/1/`.

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

    .. note:: Requires authentication.

    **Request**

    The standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.
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
