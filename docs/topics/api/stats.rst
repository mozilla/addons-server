==========
Statistics
==========

.. note::

    This API requires :doc:`authentication <auth>`.

    However this does not affect the permission model for addons.
    If you enabled public stats the data is accessible to everyone
    otherwise only authors are allowed to access the data.


The following API endpoints help you get your archived addon statistics.

---------
Archiving
---------

We are archiving statistics data that is older than one year.

We currently archive the following data:

+---------------------+--------------------+-------------------------------------------+
| name                |     model_name     | description                               |
+=====================+====================+===========================================+
| update counts       | updatecounts       | How many users updated this addon         |
+---------------------+--------------------+-------------------------------------------+
| download counts     | downloadcounts     | How many users have this addon installed  |
+---------------------+--------------------+-------------------------------------------+
| theme update counts | themeupdatecount   | How many users have this theme installed  |
+---------------------+--------------------+-------------------------------------------+


--------------------------
List monthly archived data
--------------------------

The archive is structured by year/month, to see what data is archived
for a specific month use the following api:

.. http:get:: /api/v3/statistics/archive/[string:addon-slug]/[string:year]/[string:month]/

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/statistics/archive/my-addon/2016/01/
            -H 'Authorization: JWT <jwt-token>'

    :param addon-slug: The slug for the add-on.
    :param year: The year you want to fetch.
    :param month: The month you want to fetch, please make sure to use 2 char months, e.g 01 instead of 1.

    **Response:**

    .. code-block:: json

            [
                {
                    "date": "2016-01-18",
                    "addon_id": 3615,
                    "model_name": "themeupdatecount",
                }
            ]

    :>json date: The full date for the data.
    :>json addon_id: The addon-id for the data.
    :>json model_name: The type of data.

    :statuscode 200: Archived data exists, you'll get the list of data-points.
    :statuscode 401: Authentication failed.
    :statuscode 403: You do not own this add-on.
    :statuscode 404: No data exists for this query


------------------------
Get archived data points
------------------------

Now that you have an overview of what data exists, use the following api to
access the actual data points for a specific model and date.

.. http:get:: /api/v3/statistics/archive/[string:addon-slug]/[string:year]/[string:month]/[string:day]/[string:model_name]/

    **Request:**

    .. sourcecode:: bash

        curl https://addons.mozilla.org/api/v3/statistics/archive/my-addon/2016/01/18/themeupdatecount/
            -H 'Authorization: JWT <jwt-token>'

    :param addon-slug: The slug for the add-on.
    :param year: The year you want to fetch.
    :param month: The month you want to fetch, please make sure to use 2 char months, e.g 01 instead of 1.
    :param day: The day you want to fetch, please make sure to use 2 char months, e.g 01 instead of 1.

    **Response:**

    .. code-block:: json

            [
                {
                    "date": "2016-01-18",
                    "count": 123,
                    "addon": 3615
                }
            ]

    :>json date: The full date for the data.
    :>json count: The actual statistics data.
    :>json addon: The addon id, can be used to relate and group data.

    :statuscode 200: Archived data exists, you'll get the data.
    :statuscode 401: Authentication failed.
    :statuscode 403: You do not own this add-on.
    :statuscode 404: No data exists for this query
