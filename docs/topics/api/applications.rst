============
Applications
============

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.


---------------------
Applications Versions
---------------------

.. _applications-version:

This internal endpoint allows you to create applications versions to be
referenced in add-ons manifests. It requires :ref:`authentication<api-auth>`
and a special permission.

The currently available applications versions are listed on a dedicated page:
https://addons.mozilla.org/en-US/firefox/pages/appversions/

When a valid request is made to this endpoint, AMO will create the requested
version if it didn't exist, and also attempt to create a corresponding minimum
and maximum versions. The minimum version will use the major number and minor
version from the requested version, and the maximum version will use the major
version and ``*``.

Versions that already exist will be skipped.

Examples:
    - A request to ``/api/v4/applications/firefox/42.0/`` will create versions
      ``42.0`` and ``42.*``.
    - A request to ``/api/v4/applications/firefox/42.0a1/`` will create versions
      ``42.0``, ``42.0a1``, and ``42.*``.
    - A request to ``/api/v4/applications/firefox/42.0.1/`` will create versions
      ``42.0`` and ``42.0.1``. ``42.*``.

.. http:put:: /api/v4/applications/(string:application)/(string:version)/

    **Request:**
 
      :param application: The :ref:`application <addon-detail-application>`
      :param version: The version of the application, e.g. 42.0

    **Response:**
  
      No response body will be returned on success.
  
      :statuscode 201: one or more application versions were created.
      :statuscode 202: the request was valid but no new versions were created.
      :statuscode 400: the application or version parameters were invalid.
      :statuscode 401: authentication failed.
      :statuscode 403: insufficient permissions to perform this action.
