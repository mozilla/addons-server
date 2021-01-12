================
Promoted add-ons
================

.. note::
    These APIs are subject to change at any time and are for internal use only.


--------------
Stripe Webhook
--------------

.. _v4-stripe-webhook:

This endpoint receives `event notifications
<https://stripe.com/docs/webhooks>`_ from Stripe.

    .. note::
        Requests are signed by Stripe and verified by the server.

.. http:post:: /api/v4/promoted/stripe-webhook
