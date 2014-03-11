.. _features:

============
App Features
============

API responses may be modified to exclude applications a device is unable to run.


Features List
=============

.. http:get:: /api/v1/apps/features/

    Returns a list of app features devices may require.

    **Response**

    :status 200: successfully completed.

    The response will be an object with each key representing a feature. The
    following parameters will be set for each feature:

    :param position: the position of the feature in the list
    :type position: int
    :param name: the feature name
    :type name: string
    :param description: the feature description
    :type description: string

    If a :ref:`feature profile <feature-profile-label>` is passed,
    then each feature will also contain the following:

    :param present: a boolean indicating whether the feature is present in the
        profile passed to the request.
    :type present: boolean


    Example:

    .. code-block:: json

        {
            "apps": {
                "position": 1,
                "name": "Apps",
                "description": "The app requires the `navigator.mozApps` API."
            },
            "packaged_apps": {
                "position": 2,
                "name": "Packaged apps",
                "description": "The app requires the `navigator.mozApps.installPackage` API."
            },
            ...
        }
