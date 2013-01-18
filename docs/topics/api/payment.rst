.. _payment:

======================
Payments API
======================

This API is specific to setting up and processing payments for an app in the
Marketplace.

Pay Tiers
==========

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
               "resource_uri": "/api/webpay/prices/1/"}, ...
         ]}

The result is the same as above, but in this example GBP is removed.
