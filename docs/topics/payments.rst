.. _payments:

========================================
Setting Up Payments for Apps and Add-ons
========================================

Add-on PayPal Sandbox Settings
==============================

Add-ons on AMO can accept contributions. Those contributions would run through
PayPal.

Add these URLs to your local settings to use the sandbox::

  PAYPAL_API_URL = 'https://api-3t.sandbox.paypal.com/nvp'
  PAYPAL_FLOW_URL = 'https://sandbox.paypal.com/webapps/adaptivepayment/flow/pay'
  PAYPAL_PAY_URL = 'https://svcs.sandbox.paypal.com/AdaptivePayments/'
  PAYPAL_CGI_URL = 'https://www.sandbox.paypal.com/cgi-bin/webscr'

Make yourself an account on the `PayPal developer site`_ and login. Go to the
API Credentials section (you might have to add a test seller account first)
and add the API credentials to your settings file::

  PAYPAL_CGI_AUTH = {'USER': 'yourname._1318455663_biz_api1.domain.com',
                     'PASSWORD': '<the password>',
                     'SIGNATURE': '<signature>'}
  PAYPAL_EMAIL = 'yourname._1318455663_biz@domain.com'
  PAYPAL_EMBEDDED_AUTH = PAYPAL_CGI_AUTH

Set ``PAYPAL_APP_ID`` to the registered marketplace app; ask someone in
``#amo`` if you don't know it.

To use PayPal callbacks you'll have to expose your local dev server on a real
domain to the Internet. The easiest way to do this is to use
http://progrium.com/localtunnel/ Let's say you run your dev server on port
8000. You can type this command::

  localtunnel 8000
     This localtunnel service is brought to you by Twilio.
     Port 8000 is now publicly accessible from http://4hcs.localtunnel.com ...

That sets up a proxy to your localhost on http://4hcs.localtunnel.com (or
whatever it said). Add that as your ``SITE_URL``::

  SITE_URL = 'http://4hcs.localtunnel.com'

Most of the sandbox domains require https but they don't have SSL certs! To
prepare for this, open up each one in a browser and accept the cert nag so
that it doesn't mess up the modal dialog later. For example, load
https://sandbox.paypal.com/ in your browser.

Marketplace payments
====================

Marketplace payments require Solitude
http://solitude.readthedocs.org/en/latest/ and WebPay
http://webpay.readthedocs.org/en/latest/, two other projects to process
payments.

Both of those projects allow a degree of mocking so that they don't talk to the
real payment back-ends.

You can run solitude on stackato to avoid setting it up yourself, or use the
mocked out version at http://mock-solitude.paas.allizom.org/.

Once you've set up solitude and webpay you will need to configure the
marketplace with the host::

    SOLITUDE_HOSTS = ('http://mock-solitude.paas.allizom.org/',)

You will also want to ensure that the URL ``/mozpay/`` routes to WebPay.


.. _PayPal developer site: https://developer.paypal.com/
