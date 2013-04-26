.. _home:

====
Home
====

The home page API is a specific API tailored to clients that want to show
a home page in a particular manner.

Home
====

.. http:get:: /api/v1/home/page/

    The home page of the Marketplace which is a list of featured apps and
    categories.

    **Request**:

    :param dev: the device requesting the homepage, results will be tailored to the device which will be one of: `firefoxos` (Firefox OS), `desktop`, `android` (mobile).

    This is not a standard listing page and **does not** accept the standard
    listing query parameters.

    **Response**:

    :param categories: A list of :ref:`categories <category-response-label>`.
    :param featured: A list of :ref:`apps <app-response-label>`.

Featured
========

.. http:get:: /api/v1/home/featured/

    A list of the featured apps on the Marketplace.

    **Request**

    :param dev: The device requesting the homepage, results will be tailored to the device which will be one of: `firefoxos` (Firefox OS), `desktop`, `android` (mobile).
    :param category: The id or slug of the category to filter on.

    Plus standard :ref:`list-query-params-label`.

    Region is inferred from the request.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`apps <app-response-label>`.

    :status 200: successfully completed.
