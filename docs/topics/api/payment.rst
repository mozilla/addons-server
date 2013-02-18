.. _payment:

======================
Payments API
======================

This API is specific to setting up and processing payments for an app in the
Marketplace.

Pay Tiers
==========

.. note:: Accessible via CORS_.

To get a list of pay tiers from the Marketplace::

        GET /api/webpay/prices/

This returns a list of all the prices::

        {"meta": {...}
         "objects": [{
                "name": "Tier 1",
                "prices": [
                        {"amount": "0.99", "currency": "USD"},
                        {"amount": "0.69", "currency": "GBP"}
                ],
                "localized": {},
                "resource_uri": "/api/webpay/prices/1/"}, ...
         ]}

To access just one tier, use the resource URI for that tier, for example::

        GET /api/webpay/prices/1/

Returns::

        {"name": "Tier 1",
         "prices": [
                {"amount": "0.99", "currency": "USD"},
                {"amount": "0.69", "currency": "GBP"}
         ],
         "localized": {},
         "resource_uri": "/api/webpay/prices/1/"}

The currencies can be filtered by the payment provider. Not all currencies are
available to all payment providers.

*provider* a query string parameter containing the provider name. Currently
supported values: bango

Example::

        GET /api/webpay/prices/?provider=bango

        {"meta": {...}
         "objects": [{
                "name": "Tier 1",
                "prices": [
                        {"amount": "0.99", "currency": "USD"},
               ],
               "localized": {},
               "resource_uri": "/api/webpay/prices/1/"}, ...
         ]}

The result is the same as above, but in this example GBP is removed.

Localized tier
--------------

To display a price to your user, it would be nice to know how to display a
price in the app. The Marketplace does some basic work to calculate the locale
of a user. Information that would be useful to show to your user is placed in
the localized field of the result.

Example::

    GET /api/webpay/prices/?provider=bango

With the HTTP *Accept-Language* header set to *pt-BR*, means that *localized*
will contain::

    "localized": {"amount": "10.00",
                  "currency": "BRL",
                  "locale": "R$10,00",
                  "region": "Brasil"}

The exact same request with an *Accept-Language* header set to *en-US*
returns::

    "localized": {"amount": "0.99",
                  "currency": "USD",
                  "locale": "$0.99",
                  "region": "United States"}

If a suitable currency for the region given in the request cannot be found, the
result will be empty. It could be that the currency that the Marketplace will
accept is not the currency of the country. For example, a request with
*Accept-Language* set to *fr* may result in::

    "localized": {"amount": "1.00",
                  "currency': "USD",
                  "locale": "1,00\xa0$US",
                  "region": "Monde entier"}

Please note: these are just examples to demonstrate cases. Actual results will
vary depending upon data sent and payment methods in the Marketplace.

.. _CORS: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS
