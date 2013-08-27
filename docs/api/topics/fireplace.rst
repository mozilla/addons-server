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

    A copy of :ref:`the app API <app-response-label>`.


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
