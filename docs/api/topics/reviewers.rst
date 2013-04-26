.. _reviewers:

=========
Reviewers
=========

Reviewer API provides access to the reviewer tools.

Reviewing
=========

.. note:: Requires authentication and permission to review apps.

.. warning:: Not available through CORS.

.. http:get::  /api/v1/reviewers/reviewing/

    Returns a list of apps that are being reviewed.

    **Response**:

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.

    :status 200: successfully completed.
