.. _payments:

========================================
Setting Up Payments for Apps and Add-ons
========================================

You'll have to configure your local dev environment with payment API info to
try out selling / buying an app or add-on.

PayPal Sandbox Settings
=======================

Add these URLs to your local settings to use the sandbox::

  PAYPAL_API_URL = 'https://api-3t.sandbox.paypal.com/nvp'
  PAYPAL_FLOW_URL = 'https://sandbox.paypal.com/webapps/adaptivepayment/flow/pay'
  PAYPAL_PAY_URL = 'https://svcs.sandbox.paypal.com/AdaptivePayments/'
  PAYPAL_PERMISSIONS_URL = 'https://svcs.sandbox.paypal.com/Permissions/'
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

Sell an App
===========

Make sure the waffle switch ``marketplace`` is flipped on then create a test
*seller* account on the `PayPal developer site`_. This seller account has to
be different from the one linked to the API Credentials that you added in the
above settings.

Submit an app. On the last screen you'll see a link to enroll your app in the
marketplace. Enter the email for the test seller account and enter any email
as the support contact. When you click continue, you'll get a message that you
need to grant PayPal access to make refunds. Follow that link and log in with
the seller account you just created. If you were already logged in with the
other account you might have to log out first. When this is successful it will
post to your callback and you can continue enrolling your app in the
marketplace.

Buy an App
==========

Create a test *buyer* account on the `PayPal developer site`_. Create a new
AMO user account that you will use to buy apps with. Go to an app page, click
the buy button, then enter the username / password of the test buyer account.

.. _`PayPal developer site`: https://developer.paypal.com/
