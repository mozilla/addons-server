============
Transactions
============

This endpoint is for getting more details about a Solitude transaction.

Transaction
===========

.. note:: Requires authentication and the RevenueStats:View permission.

.. http:get:: /api/v1/transactions/(string:transaction_id)/

    Gets information about the transaction.

    **Request**

    Empty

    **Response**

    .. code-block:: json

        {
            "id": "abcdef-abcd",
            "app_id": 123,
            "amount_USD": "1.99",
            "type": 'purchase'
        }

    :param id: The Solitude transaction ID.
    :type id: string
    :param app_id: The ID of the app.
    :type app_id: integer
    :param amount_USD: The amount of the transaction in USD.
    :type amount_USD: string
    :param type: The transaction type. One of: 'Chargeback, 'Other', 'Purchase', 'Refund', 'Voluntary'.

