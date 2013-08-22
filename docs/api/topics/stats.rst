======================
Marketplace Statistics
======================

These endpoints supply statistical data for aspects of the Marketplace.
This is a read-only resource intended to be consumed by various charting
libraries.


Global Statistics
=================

.. http:get:: /api/v1/stats/global/(string:metric)/

    Retrieve data for the given metric.

    .. note:: Authentication is required. See the
        :ref:`shared secret docs <sharedsecret>`.

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string

    Depending on the `metric` there may be additional query string parameters.

    **Response**:

    .. code-block:: json

         {
            "objects": [
                {
                    "count": 12,
                    "date": "2013-08-01"
                },
                {
                    "count": 25,
                    "date": "2013-08-02"
                },
                {
                    "count": 32,
                    "date": "2013-08-03"
                },
                {
                    "count": 4,
                    "date": "2013-08-04"
                },
                ...
            ]
        }

Metrics
-------

Provided are these metrics:

Apps added by packaging type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The number of apps added each day over time, filtered by package type.

.. http:get:: /api/v1/stats/global/apps_added_by_package/

    **Request**:

    Along with the above arguments, this also takes:

    :param region: Filter by the provided :ref:`region <regions>` slug (e.g., "us").
    :type region: string
    :param packaging_type: Filter by the packaging type. One of 'hosted',
        'packaged'.
    :type packaging_type: string

Apps added by premium type
~~~~~~~~~~~~~~~~~~~~~~~~~~

The number of apps added each day over time, filtered by premium type.

.. http:get:: /api/v1/stats/global/apps_added_by_premium/

    **Request**:

    Along with the above arguments, this also takes:

    :param region: Filter by the provided :ref:`region <regions>` slug (e.g., "us").
    :type region: string
    :param premium_type: Filter by the premium type. One of 'free',
        'free-inapp', 'premium', 'premium-inapp', 'other'.
    :type premium_type: string

Total developers
~~~~~~~~~~~~~~~~

The total number of developers over time.

.. http:get:: /api/v1/stats/global/total_developers/

Total visits
~~~~~~~~~~~~

The total number of visits to Marketplace over time.

.. http:get:: /api/v1/stats/global/total_visits/
