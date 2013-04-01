.. _reviewers:

=============
Reviewers API
=============

Reviewer API provides access to the reviewer tools.

Reviewing
=========

.. note:: Requires authentication and permission to review apps.

.. warning:: Not available through CORS.

.. http:get::  /api/reviewers/reviewing/

   Returns a list of apps that are being reviewed.

   **Request**:

   .. sourcecode:: http

      GET /api/reviewers/reviewing/

   **Response**:

   .. sourcecode:: http

      {
        "meta": {
            "previous": None, ...
        },
        "objects': [
            {
                "resource_uri": "/api/apps/app/337141/"
            }
        ]
      }

   :statuscode 200: no error
