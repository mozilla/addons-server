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

Apps available by packaging type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The number of apps available each day over time for each app package type.

.. http:get:: /api/v1/stats/global/apps_available_by_package/

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

Apps available by premium type
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The number of apps available each day over time, filtered by premium type.

.. http:get:: /api/v1/stats/global/apps_available_by_premium/

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

Apps installed
~~~~~~~~~~~~~~

The number of apps installed each day over time, optionally filtered by
region.

.. note:: Zero values are not stored.

.. http:get:: /api/v1/stats/global/apps_installed/

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string
    :param region: Optionally filter by the provided :ref:`region <regions>` slug (e.g., "us").
    :type region: string

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

Ratings
~~~~~~~

The number of app ratings each day to Marketplace over time.

.. http:get:: /api/v1/stats/global/ratings/

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
                    "count": 23,
                    "date": "2013-08-02"
                },
                ...
            ],
        }

Abuse Reports
~~~~~~~~~~~~~

The number of abuse reports each day to Marketplace over time.

.. http:get:: /api/v1/stats/global/abuse_reports/

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
                    "count": 3,
                    "date": "2013-08-01"
                },
                {
                    "count": 0,
                    "date": "2013-08-02"
                },
                ...
            ],
        }

Gross Revenue
~~~~~~~~~~~~~

The gross revenue of apps purchased over time.

.. http:get:: /api/v1/stats/global/revenue/

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
                    "count": "1.99",
                    "date": "2013-08-01"
                },
                {
                    "count": "2.98",
                    "date": "2013-08-02"
                },
                ...
            ],
        }


Per-app Statistics
==================

Statistics per public app in the Marketplace.

Metrics
-------

Provided are these metrics:

Installs
~~~~~~~~

The number of apps installs each day over time, optionally filtered by
region.

.. note:: Zero values are not stored.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/installs/

    **Request**:

    :param start: The starting date in "YYYY-MM-DD" format.
    :type start: string
    :param end: The ending date in "YYYY-MM-DD" format.
    :type end: string
    :param interval: The interval. One of the following: 'day', 'week',
                     'month', 'quarter', 'year'.
    :type interval: string
    :param region: Optionally filter by the provided :ref:`region <regions>` slug (e.g., "us").
    :type region: string

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

Visits
~~~~~~

The number of page visits each day over time.

.. note:: Zero values are not stored.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/visits/

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

Ratings
~~~~~~~

The number of app ratings each day for this app over time.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/ratings/

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
                    "count": 8,
                    "date": "2013-08-02"
                },
                ...
            ],
        }

Average ratings
~~~~~~~~~~~~~~~

The average rating for this app over time.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/average_rating/

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
                    "count": 3.5,
                    "date": "2013-08-01"
                },
                {
                    "count": 3.75,
                    "date": "2013-08-02"
                },
                ...
            ],
        }

Abuse Reports
~~~~~~~~~~~~~

The number of abuse reports each day for this app over time.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/abuse_reports/

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
                    "count": 3,
                    "date": "2013-08-01"
                },
                {
                    "count": 0,
                    "date": "2013-08-02"
                },
                ...
            ],
        }

Gross Revenue
~~~~~~~~~~~~~

The gross revenue of app purchases over time.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/revenue/

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
                    "count": "1.99",
                    "date": "2013-08-01"
                },
                {
                    "count": "2.98",
                    "date": "2013-08-02"
                },
                ...
            ],
        }


Totals Statistics
=================

Statistical information about metrics tracked. The information includes
the total, minimum and maximum, and other statistical calculations for
various metrics tracked.

Metrics
-------

Provided are the following metrics.

Global totals
~~~~~~~~~~~~~

Statistical information about global metrics.

.. http:get:: /api/v1/stats/global/totals/

    **Response**:

    .. code-block:: json

        {
            "abuse_reports": {
                "max": 2.0,
                "mean": 1.5,
                "min": 1.0,
                "std_deviation": 0.5,
                "sum_of_squares": 10.0,
                "total": 6.0,
                "variance": 0.25
            },
            "installs": {
                "max": 2716.0,
                "mean": 14.313328064711078,
                "min": 1.0,
                "std_deviation": 55.293387141332197,
                "sum_of_squares": 70173830.0,
                "total": 307894.0,
                "variance": 3057.3586615612408
            },
            "ratings": {
                "max": 1.0,
                "mean": 1.0,
                "min": 1.0,
                "std_deviation": 0.0,
                "sum_of_squares": 2.0,
                "total": 2.0,
                "variance": 0.0
            }
        }

Per-app totals
~~~~~~~~~~~~~~

Statistical information about per-app metrics.

.. http:get:: /api/v1/stats/app/(int:id)|(string:slug)/totals/

    **Response**:

    .. code-block:: json

        {
            "abuse_reports": {
                "max": 1.0,
                "mean": 1.0,
                "min": 1.0,
                "std_deviation": 0.0,
                "sum_of_squares": 2.0,
                "total": 2.0,
                "variance": 0.0
            },
            "installs": {
                "max": 43.0,
                "mean": 7.730769230769231,
                "min": 1.0,
                "std_deviation": 7.5483087736492305,
                "sum_of_squares": 21247.0,
                "total": 1407.0,
                "variance": 56.976965342349956
            },
            "ratings": {
                "max": 1.0,
                "mean": 1.0,
                "min": 1.0,
                "std_deviation": 0.0,
                "sum_of_squares": 2.0,
                "total": 2.0,
                "variance": 0.0
            }
        }
