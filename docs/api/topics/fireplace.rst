.. _fireplace:

=========
Fireplace
=========

Fireplace is the consumer client for the Marketplace. It has some special
API's. These are *not recommended* for consumption by other clients and can
change in conjunction with the Fireplace client.

App
===

.. http:get:: /api/v1/fireplace/app/

    A copy of :ref:`the app API <app-response-label>`. The response only
    contains the specific subset of fields Fireplace needs.


Error reporter
==============

.. http:post:: /api/v1/fireplace/report_error

    An entry point for reporting client-side errors via Sentry.

    **Request**

    Takes a `sentry.interfaces.Exception <https://sentry.readthedocs.org/en/latest/developer/interfaces/index.html#sentry.interfaces.Exception>`_ JSON object.

    Example:

    .. code-block:: json

        [{
            "value": "important problem",
            "stacktrace": {
                "frames": [{
                       "abs_path": "/real/file/name.py"
                        "filename": "file/name.py",
                        "function": "myfunction",
                        "vars": {
                            "key": "value"
                        },
                        "pre_context": [
                            "line1",
                            "line2"
                        ],
                        "context_line": "line3",
                        "lineno": 3,
                        "in_app": true,
                        "post_context": [
                            "line4",
                            "line5"
                        ],
                    }]
                }
        }]

    **Response**

    :status 204: Message sent.

Search
======

.. http:get:: /api/v1/fireplace/search/

    A copy of :ref:`the search API <search-api>`. Like the App API above, the
    response only contains the specific subset of fields Fireplace needs.

Featured Search
===============

.. http:get:: /api/v1/fireplace/search/featured/

    A copy of :ref:`the featured search API <featured-search-api>`. Like the
    App API above, the response contains the specific subset of fields Fireplace
    needs.


Consumer Information
====================

.. http:get:: /api/v1/fireplace/consumer-info/

    Return information about the client making the request.

    **Response**

    :param region: The region slug for this client.
    :type region: string

    If user authentication information is passed to the request, the following
    will also be added to the response:

    :param apps.developed: IDs of apps the user has developed.
    :type active: array
    :param apps.installed: IDs of apps the user has installed.
    :type active: array
    :param apps.purchased: IDs of apps the user has purchased.
    :type active: array
