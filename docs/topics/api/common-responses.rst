====================
Common API Responses
====================

There are some common API responses that you can expect to receive at times.

.. http:get:: /api/v3/...

    :statuscode 401: Authentication is required or failed.
    :statuscode 403: You are not permitted to perform this action.
    :statuscode 404: The requested resource could not be found.
    :statuscode 500: An unknown error occurred.
    :statuscode 503:
        The site is in maintenance mode and this operation is not permitted.
