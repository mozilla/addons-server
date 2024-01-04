========
Services
========

.. note::
  
      These APIs are not frozen and can change at any time without warning.
      See :ref:`the API versions available<api-versions-list>` for alternatives
      if you need stability.


These special endpoints are meant for internal debugging, not for general use.

-----------
Client Info
-----------

.. _`api-client_info`:

This endpoints returns basic information about the request environement. It is
useful to test what the application sees behind the CDN and Load Balancers, as
both will alter some of the HTTP headers / WSGI variables.

Because it can return IP addresses, it only works in the ``addons-dev.allizom.org``
environment.

.. http:get:: /api/v5/services/client_info/

    :>json string HTTP_USER_AGENT: The User-Agent HTTP header.
    :>json string HTTP_X_COUNTRY_CODE: The ISO 3166-1 alpha-2 country code corresponding to the IP that made the request.
    :>json string HTTP_X_FORWARDED_FOR: The X-Forwarded-For HTTP header.
    :>json string REMOTE_ADDR: The IP address of the client.
    :>json object POST: POST data of the request.
    :>json object GET: GET data of the request.

---
403
---

.. _`api-403`:

This endpoint returns a basic 403 error response.

.. http:get:: /api/v5/services/403/

    :>json string detail: Message explaining the error.

---
404
---

.. _`api-404`:

This endpoint returns a basic 404 error response.

.. http:get:: /api/v5/services/404/

    :>json string detail: Message explaining the error.

---
500
---

.. _`api-500`:

This endpoint returns a basic 500 error response. The ``traceback`` property in
the response is only present on local environments, when ``DEBUG`` is ``True``.

.. http:get:: /api/v5/services/500/

    :>json string detail: Message explaining the error.
    :>json string traceback: Traceback of the error.
