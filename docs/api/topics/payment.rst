.. _payment:

========
Payments
========

This API is specific to setting up and processing payments for an app in the
Marketplace.

.. _payment-account-label:

Configuring payment accounts
============================

Payment accounts can be added and listed.

.. note:: Authentication is required.

.. http:post:: /api/v1/payments/account/

    **Request**

    :param account_name: Account name.
    :type account_name: string
    :param companyName: Company name.
    :type companyName: string
    :param vendorName: Vendor name.
    :type vendorName: string
    :param financeEmailAddress: Financial email.
    :type financeEmailAddress: string
    :param supportEmailAddress: Support email.
    :type supportEmailAddress: string
    :param address1: Address.
    :type address1: string
    :param address2: Second line of address.
    :type address2: string
    :param addressCity: City/municipality.
    :type addressCity: string
    :param addressState: State/province/region.
    :type addressState: string
    :param addressZipCode: Zip/postal code.
    :type addressZipCode: string
    :param countryIso: Country.
    :type countryIso: string
    :param vatNumber: VAT number.
    :type vatNumber: string

    *the following fields cannot be modified after account creation*

    :param bankAccountPayeeName: Account holder name.
    :type bankAccountPayeeName: string
    :param bankAccountNumber: Bank account number.
    :type bankAccountNumber: string
    :param bankAccountCode: Bank account code.
    :type bankAccountCode: string
    :param bankName: Bank name.
    :param bankAddress1: Bank address.
    :type bankAddress1: string
    :param bankAddress2: Second line of bank address.
    :type bankAddress2: string
    :param bankAddressState: Bank state/province/region.
    :type bankAddressState: string
    :param bankAddressZipCode: Bank zip/postal code.
    :type bankAddressZipCode: string
    :param bankAddressIso: Bank country.
    :type bankAddressIso: string
    :param adminEmailAddress: Administrative email.
    :type adminEmailAddress: string
    :param currencyIso: Currency you prefer to be paid in.
    :type currencyIso: string

    **Response**

    :status code: 201 successfully created.

.. http:put:: /api/v1/payments/account/(int:id)/

    **Request**

    :param account_name: Account name.
    :type  account_name: string
    :param vendorName: Vendor name.
    :type vendorName: string
    :param financeEmailAddress: Financial email.
    :type financeEmailAddress: string
    :param supportEmailAddress: Support email.
    :type supportEmailAddress: string
    :param address1: Address.
    :type address1: string
    :param address2: Second line of address.
    :type address2: string
    :param addressCity: City/municipality.
    :type addressCity: string
    :param addressState: State/province/region.
    :type addressState: string
    :param addressZipCode: Zip/postal code.
    :type addressZipCode: string
    :param countryIso: Country.
    :type countryIso: string
    :param vatNumber: VAT number.
    :type vatNumber: string

    **Response**

    :status 204: successfully updated.

.. http:delete:: /api/v1/payments/account/(int:id)/

    .. warning:: This can potentially remove all your apps from sale.

    If you delete a payment account then all apps which use that account can
    no longer process payments. All apps that use this payment account will
    be moved into the incomplete state. Each of those apps will need to
    resubmitted to process payments.

    **Response**

    :status 204: successfully deleted.
    :status 409: shared accounts cannot be deleted whilst apps are using them.

.. http:get:: /api/v1/payments/account/

    **Request**

    The standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`accounts <payment-account-response-label>`.
    :type objects: array

.. _payment-account-response-label:

.. http:get:: /api/v1/payments/account/(int:id)/

    **Response**

    An account object, see below for an example.

    :status 200: successfully completed.

    Example:

    .. code-block:: json

        {
             "account_name": "account",
             "address1": "123 Main St",
             "addressCity": "Byteville",
             "addressPhone": "605-555-1212",
             "addressState": "HX",
             "addressZipCode": "55555",
             "adminEmailAddress": "apps_admin@example.com",
             "companyName": "Example Company",
             "countryIso": "BRA",
             "currencyIso": "EUR",
             "financeEmailAddress": "apps_accounts@example.com",
             "resource_uri": "/api/v1/payments/account/175/",
             "supportEmailAddress": "apps_support@example.com",
             "vendorName": "vendor"
        }

Upsell
======

.. http:post:: /api/v1/payments/upsell/

    Creates an upsell relationship between two apps, a free and premium one.
    Send the URLs for both apps in the post to create the relationship.

    **Request**

    :param free: URL to the free app.
    :type free: string
    :param premium: URL to the premium app.
    :type premium: string

    **Response**

    :status 201: sucessfully created.

.. _upsell-response-label:

.. http:get:: /api/v1/payments/upsell/(int:id)/

    **Response**

    .. code-block:: json

        {"free": "/api/v1/apps/app/1/",
         "premium": "/api/v1/apps/app/2/"}

    :param free: URL to the free app.
    :type free: string
    :param premium: URL to the premium app.
    :type premium: string

.. http:patch:: /api/v1/payments/upsell/(int:id)/

    Alter the upsell from free to premium by passing in new free and premiums.

    **Request**

    :param free: URL to the free app.
    :type free: string
    :param premium: URL to the premium app.
    :type premium: string

    **Response**

    :status 200: sucessfully altered.

.. http:delete:: /api/v1/payments/upsell/(int:id)/

    To delete the upsell relationship.

    **Response**

    :status 204: sucessfully deleted.

Payment accounts
================

.. http:post:: /api/v1/payments/app/

    Creates a relationship between the payment account and the app.

    **Request**

    :param app: URL to the premium app.
    :type app: string
    :param account: URL to the account.
    :type account: string

    Once created, the app is not changeable.

    **Response**

    :status 201: sucessfully created.
    :param app: URL to the premium app.
    :type app: string
    :param account: URL to the account.
    :type account: string

.. http:patch:: /api/v1/payments/app/(int:id)/

    Alter the payment account being used.

    **Request**

    :param app: URL to the premium app. Must be unchanged.
    :type app: string
    :param account: URL to the account.
    :type account: string

    **Response**

    :status 200: sucessfully updated.
    :param app: URL to the premium app.
    :type app: string
    :param account: URL to the account.
    :type account: string

Preparing payment
=================

Produces the JWT that is passed to `navigator.mozPay`_.

.. note:: Authentication is required.

.. http:post:: /api/v1/webpay/prepare/

    **Request**

    :param string app: the id or slug of the app to be purchased.

    **Response**

    .. code-block:: json

        {
            "app": "337141: Something Something Steamcube!",
            "contribStatusURL": "https://marketplace.firefox.com/api/v1/webpay/status/123/",
            "resource_uri": "",
            "webpayJWT": "eyJhbGciOiAiSFMy... [truncated]",
        }

    :param webpayJWT: the JWT to pass to `navigator.mozPay`_
    :type webpayJWT: string
    :param contribStatusURL: the URL to poll for
        :ref:`payment-status-label`.
    :type contribStatusURL: string

    :status 201: successfully completed.
    :status 401: not authenticated.
    :status 403: app cannot be purchased.
    :status 409: app already purchased.

Signature Check
===============

Retrieve a JWT that can be used to check the signature for making payments.
This is intended for system health checks and requires no authorization.
You can pass the retrieved JWT to the `WebPay`_ API to verify its signature.

.. http:post:: /api/v1/webpay/sig_check/

    **Request**

    No parameters are necessary.

    **Response**

    .. code-block:: json

        {
            "sig_check_jwt": "eyJhbGciOiAiSFMyNT...XsgG6JKCSw"
        }

    :param sig_check_jwt: a JWT that can be passed to `WebPay`_.
    :type sig_check_jwt: string

    :status 201: successfully created resource.

.. _payment-status-label:

Payment status
==============

.. note:: Authentication is required.

.. http:get:: /api/v1/webpay/status/(string:uuid)/

    **Request**

    :param uuid: the uuid of the payment. This URL is returned as the
        ``contribStatusURL`` parameter of a call to *prepare*.
    :type uuid: string

    **Response**

    :param status: ``complete`` or ``incomplete``
    :type status: string

    :status 200: request processed, check status for value.
    :status 401: not authenticated.
    :status 403: not authorized to view details on that transaction.

Installing
==========

When an app is installed from the Marketplace, call the install API. This will
record the install.

Free apps
---------

.. http:post:: /api/v1/installs/record/

    **Request**:

    :param app: the id or slug of the app being installed.
    :type app: int|string

    **Response**:

    :statuscode 201: successfully completed.
    :statuscode 202: an install was already recorded for this user and app, so
        we didn't bother creating another one.
    :statuscode 403: app is not public, install not allowed.


Premium apps
------------

.. note:: Authentication is required.

.. http:post:: /api/v1/receipts/install/

    Returns a receipt if the app is paid and a receipt should be installed.

    **Request**:

    :param app: the id or slug of the app being installed.
    :type app: int|string

    **Response**:

    .. code-block:: json

        {"receipt": "eyJhbGciOiAiUlM1MT...[truncated]"}

    :statuscode 201: successfully completed.
    :statuscode 401: not authenticated.
    :statuscode 402: payment required.
    :statuscode 403: app is not public, install not allowed.

Developers
~~~~~~~~~~

Developers of the app will get a special developer receipt that is valid for
24 hours and does not require payment. See also `Test Receipts`_.

Reviewers
~~~~~~~~~

Reviewers should not use this API.

Test Receipts
=============

Returns test receipts for use during testing or development. The returned
receipt will have type `test-receipt`. Only works for hosted apps.

.. http:post:: /api/v1/receipts/test/

    Returns a receipt suitable for testing your app.

    **Request**:

    :param manifest_url: the fully qualified URL to the manifest, including
        protocol.
    :type manifest_url: string
    :param receipt_type: one of ``ok``, ``expired``, ``invalid`` or ``refunded``.
    :type receipt_type: string

    **Response**:

    .. code-block:: json

        {"receipt": "eyJhbGciOiAiUlM1MT...[truncated]"}

    :status 201: successfully completed.

Receipt reissue
===============

This is currently not implemented `awaiting bug <https://bugzilla.mozilla.org/show_bug.cgi?id=757226>`_. It will
be used for `replacing receipts <https://wiki.mozilla.org/Apps/WebApplicationReceiptRefresh>`_.

.. http:post:: /api/v1/receipts/reissue/

    **Response**:

    .. code-block:: json

        {"receipt": "", "status": "not-implemented"}

    :param receipt: the receipt, currently blank.
    :type receipt: string
    :param status: one of ``not-implemented``.
    :type status: string
    :status 200: successfully completed.


Pay Tiers
==========

.. http:get:: /api/v1/webpay/prices/

    Gets a list of pay tiers from the Marketplace.

    **Request**

    :param provider: (optional) the payment provider. Current values: *bango*
    :type provider: string

    The standard :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`pay tiers <pay-tier-response-label>`.
    :type objects: array
    :statuscode 200: successfully completed.

.. _pay-tier-response-label:

.. http:get:: /api/v1/webpay/prices/(int:id)/

    Returns a specific pay tier.

    **Response**

    .. code-block:: json

        {
            "name": "Tier 1",
            "pricePoint": "1",
            "prices": [{
                "price": "0.99",
                "method": 2,
                "region": 2,
                "tier": 26,
                "provider": 1,
                "currency": "USD",
                "id": 1225,
                "dev": true,
                "paid": true
            }, {
                "price": "0.69",
                "method": 2,
                "region": 14,
                "tier": 26,
                "provider": 1,
                "currency": "DE",
                "id": 1226,
                "dev": true,
                "paid": true
            }],
            "localized": {},
            "resource_uri": "/api/v1/webpay/prices/1/",
            "created": "2011-09-29T14:15:08",
            "modified": "2013-05-02T14:43:58"
        }

    :param region: a :ref:`region <region-response-label>`.
    :type region: int
    :param carrier: a :ref:`carrier <carrier-response-label>`.
    :type carrier: int
    :param localized: see `Localized tier`.
    :type localized: object
    :param tier: the id of the tier.
    :type tier: int
    :param method: the payment method.
    :type method: int
    :param provider: payment provider, currently only ``1`` is supported.
    :type provider: int
    :param pricePoint: this is the value used for in-app payments.
    :type pricePoint: string
    :param dev: if ``true`` the tier will be shown to the developer during
        app configuration.
    :type dev: boolean
    :param paid: if ``true`` this tier can be used for payments by users.
    :type paid: boolean
    :statuscode 200: successfully completed.


.. _localized-tier-label:

Localized tier
--------------

To display a price to your user, it would be nice to know how to display a
price in the app. The Marketplace does some basic work to calculate the locale
of a user. Information that would be useful to show to your user is placed in
the localized field of the result.

A request with the HTTP *Accept-Language* header set to *pt-BR*, means that
*localized* will contain:

    .. code-block:: json

        {
            "localized": {
                "amount": "10.00",
                "currency": "BRL",
                "locale": "R$10,00",
                "region": "Brasil"
            }
        }

The exact same request with an *Accept-Language* header set to *en-US*
returns:

    .. code-block:: json

        {
            "localized": {
                "amount": "0.99",
                "currency": "USD",
                "locale": "$0.99",
                "region": "United States"
            }
        }

If a suitable currency for the region given in the request cannot be found, the
result will be empty. It could be that the currency that the Marketplace will
accept is not the currency of the country. For example, a request with
*Accept-Language* set to *fr* may result in:

    .. code-block:: json

        {
            "localized": {
                "amount": "1.00",
                "currency": "USD",
                "locale": "1,00\xa0$US",
                "region": "Monde entier"
            }
        }

Please note: these are just examples to demonstrate cases. Actual results will
vary depending upon data sent and payment methods in the Marketplace.

Product Icons
=============

Authenticated clients like `WebPay`_ need to display external product images in a
safe way. This API lets WebPay cache and later retrieve icon URLs.

.. note:: All write requests (``POST``, ``PATCH``) require authenticated users to have the
    ``ProductIcon:Create``  permission.


.. http:get:: /api/v1/webpay/product/icon/

    Gets a list of cached product icons.

    **Request**

    :param ext_url: Absolute external URL of product icon that was cached.
    :type ext_url: string
    :param ext_size: Height and width pixel value that was declared for this icon.
    :type ext_size: int
    :param size: Height and width pixel value that this icon was resized to.

    You may also request :ref:`list-query-params-label`.

    **Response**

    :param meta: :ref:`meta-response-label`.
    :type meta: object
    :param objects: A :ref:`listing <objects-response-label>` of :ref:`product icons <product-icon-response-label>`.
    :type objects: array
    :statuscode 200: successfully completed.

.. _product-icon-response-label:

.. http:get:: /api/v1/webpay/product/icon/(int:id)/

    **Response**

    .. code-block:: json

        {
            "url": "http://marketplace-cdn/product-icons/0/1.png",
            "resource_uri": "/api/v1/webpay/product/icon/1/",
            "ext_url": "http://appserver/media/icon.png",
            "ext_size": 64,
            "size": 64
        }

    :param url: Absolute URL of the cached product icon.
    :type url: string
    :statuscode 200: successfully completed.

.. http:post:: /api/v1/webpay/product/icon/

    Post a new product icon URL that should be cached.
    This schedules an icon to be processed but does not return any object data.

    **Request**

    :param ext_url: Absolute external URL of product icon that should be cached.
    :type ext_url: string
    :param ext_size: Height and width pixel value that was declared for this icon.
    :type ext_size: int
    :param size: Height and width pixel value that this icon should be resized to.
    :type size: int

    **Response**

    :statuscode 202: New icon accepted. Deferred processing will begin.
    :statuscode 400: Some required fields were missing or invalid.
    :statuscode 401: The API user is unauthorized to cache product icons.


Transaction failure
===================

.. note:: Requires authenticated users to have the Transaction:NotifyFailure
    permission. This API is used by internal clients such as WebPay_.

.. http:patch:: /api/v1/webpay/failure/(int:transaction_id)/

    Notify the app developers that our attempts to call the postback or
    chargebacks URLs from `In-app Payments`_ failed. This will send an
    email to the app developers.

    **Response**

    :status 202: Notification will be sent.
    :statuscode 403: The API user is not authorized to report failures.

.. _CORS: https://developer.mozilla.org/en-US/docs/HTTP/Access_control_CORS
.. _WebPay: https://github.com/mozilla/webpay
.. _In-app Payments: https://developer.mozilla.org/en-US/docs/Apps/Publishing/In-app_payments
.. _navigator.mozPay: https://wiki.mozilla.org/WebAPI/WebPayment
