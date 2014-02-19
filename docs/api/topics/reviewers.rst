.. _reviewers:

=========
Reviewers
=========

Reviewer API provides access to the reviewer tools.

Reviewing
=========

.. note:: Requires authentication and permission to review apps.

.. http:get::  /api/v1/reviewers/search/

    Performs a search just like the regular Search API, but customized with
    extra parameters and different (smaller) apps objects returned, containing
    only the information that is required for reviewer tools.

    **Response**:

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <reviewers-app-response-label>`.
    :type objects: array

    :status 200: successfully completed.

    .. _reviewers-app-response-label:

    Each app in the response will contain the following:

    :param device_types: a list of the device types at least one of:
        `desktop`, `mobile`, `tablet`, `firefoxos`. `mobile` and `tablet` both
        refer to Android mobile and tablet. As opposed to Firefox OS.
    :type device_types: array
    :param id: the app's id.
    :type id: int
    :param is_escalated: a boolean indicating whether this app is currently
        in the escalation queue or not.
    :type is_escalated: boolean
    :param is_packaged: a boolean indicating whether the app is packaged or
        not.
    :type is_packaged: boolean
    :param latest_version: an array containing the following information about
        the app's latest version:
    :type latest_version: object
    :param latest_version.has_editor_comment: a boolean indicathing whether
        that version contains comments from a reviewer.
    :type latest_version.has_editor_comment: boolean
    :param latest_version.has_info_request: a boolean indicathing whether that
        version contains an information request from a reviewer.
    :type latest_version.has_info_request: boolean
    :param latest_version.is_privileged: a boolean indicating whether this
        version is a privileged app or not.
    :type latest_version.is_privileged: boolean
    :param latest_version.status: an int representing the version status. Can
        be different from the app status, since the latest_version can be
        different from the latest public one.
    :type latest_version.status: int
    :param name: the name of the app
    :type name: string
    :param premium_type: one of ``free``, ``premium``, ``free-inapp``,
        ``premium-inapp``. If ``premium`` or ``premium-inapp`` the app should
        be bought, check the ``price`` field to determine if it can.
    :type premium_type: string
    :param price: If it is a paid app this will be a string representing
        the price in the currency calculated for the request. If ``0.00`` then
        no payment is required, but the app requires a receipt. If ``null``, a
        price cannot be calculated for the region and cannot be bought.
        Example: 1.00
    :type price: string|null
    :param name: the URL slug for the app
    :type name: string
    :param status: an int representing the version status.
    :type latest_version.status: int


.. note:: Requires authentication and permission to review apps.

.. warning:: Not available through CORS.

.. http:get::  /api/v1/reviewers/reviewing/

    Returns a list of apps that are being reviewed.

    **Response**:

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.
    :type objects: array

    :status 200: successfully completed.


.. note:: Requires authentication and permission to review apps.

.. warning:: Not available through CORS.

.. http:post::  /api/v1/reviewers/app/(int:id)|(string:slug)/token

    Returns a short-lived token that can be used to access the
    mini-manifest. Use this token as a query-string parameter to the
    mini-manifest URL named "token" within 60 seconds.

    **Response**:

    :param token: The token.
    :type meta: string

    :status 200: successfully completed.
