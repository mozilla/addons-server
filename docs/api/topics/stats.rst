==========
Statistics
==========

These endpoints supply statistical data for aspects of the Marketplace.
This is a read-only resource intended to be consumed by various charting
libraries.


Global Statistics
=================

Statistics across the Marketplace as a whole.

Metrics
-------

Provided are these metrics:

Apps added by packaging type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The number of apps added each day over time for each app package type.

.. http:get:: /api/v1/stats/global/apps_added_by_package/

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string
    :param region: Filter by the provided :ref:`region <regions>` slug (e.g., "us").
    :type region: string

    **Response**:

    .. code-block:: json

         {
            "hosted": [
                {
                    "count": 12,
                    "date": "2013-08-01"
                },
                {
                    "count": 25,
                    "date": "2013-08-02"
                },
                ...
            ],
            "packaged": [
                {
                    "count": 32,
                    "date": "2013-08-01"
                },
                {
                    "count": 4,
                    "date": "2013-08-02"
                },
                ...
            ]
        }

Apps added by premium type
~~~~~~~~~~~~~~~~~~~~~~~~~~

The number of apps added each day over time, filtered by premium type.

.. http:get:: /api/v1/stats/global/apps_added_by_premium/

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string
    :param region: Filter by the provided :ref:`region <regions>` slug (e.g., "us").
    :type region: string

    **Response**:

    .. code-block:: json

         {
            "free": [
                {
                    "count": 12,
                    "date": "2013-08-01"
                },
                {
                    "count": 25,
                    "date": "2013-08-02"
                },
                ...
            ],
            "free-inapp": [
                {
                    "count": 32,
                    "date": "2013-08-01"
                },
                {
                    "count": 4,
                    "date": "2013-08-02"
                },
                ...
            ],
            "premium": [
                {
                    "count": 32,
                    "date": "2013-08-01"
                },
                {
                    "count": 4,
                    "date": "2013-08-02"
                },
                ...
            ],
            "premium-inapp": [
                {
                    "count": 32,
                    "date": "2013-08-01"
                },
                {
                    "count": 4,
                    "date": "2013-08-02"
                },
                ...
            ],
            "other": [
                {
                    "count": 32,
                    "date": "2013-08-01"
                },
                {
                    "count": 4,
                    "date": "2013-08-02"
                },
                ...
            ]
        }

Total developers
~~~~~~~~~~~~~~~~

The total number of developers over time.

.. http:get:: /api/v1/stats/global/total_developers/

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string

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
                ...
            ],
        }

Total visits
~~~~~~~~~~~~

The total number of visits to Marketplace over time.

.. http:get:: /api/v1/stats/global/total_visits/

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string

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
                ...
            ],
        }
