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
