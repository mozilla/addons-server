=====================
Applications Versions
=====================

.. note::

    These APIs are not frozen and can change at any time without warning.
    See :ref:`the API versions available<api-versions-list>` for alternatives
    if you need stability.

----
List
----

.. _applications-version-list:

This endpoint allows you to list all versions that AMO currently supports for a given application.

.. http:get:: /api/v5/applications/(string:application)/

    :param application: The :ref:`application <addon-detail-application>`,
    :>json string guid: The GUID for the requested application.
    :>json array versions: An array of all the supported version strings.


------
Create
------

.. _applications-version-create:

This internal endpoint allows you to create applications versions to be
referenced in add-ons manifests. It requires :ref:`authentication<api-auth>`
and a special permission.

The currently available applications versions are :ref:`available to list<applications-version-list>`.

When a valid request is made to this endpoint, AMO will create the requested
version if it didn't exist, and also attempt to create a corresponding minimum
and maximum versions. The minimum version will use the major number and minor
version from the requested version, and the maximum version will use the major
version and ``*``.

.. note::

  Regardless of what application is passed in the URL, this endpoint will
  always create versions for both Firefox and Firefox For Android.

Versions that already exist will be skipped.

Examples:
    - A request to ``/api/v5/applications/firefox/42.0/`` will create versions
      ``42.0`` and ``42.*``.
    - A request to ``/api/v5/applications/firefox/42.0a1/`` will create versions
      ``42.0``, ``42.0a1``, and ``42.*``.
    - A request to ``/api/v5/applications/firefox/42.0.1/`` will create versions
      ``42.0`` and ``42.0.1``. ``42.*``.

.. http:put:: /api/v5/applications/(string:application)/(string:version)/

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
