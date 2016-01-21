============
External API
============

This shows you how to use the `addons.mozilla.org <https://addons.mozilla.org/en-US/firefox/>`_
API at ``/api/v3/`` which is hosted at the following URLs:

===========  =========================================
Environment  URL
===========  =========================================
Production   ``https://addons.mozilla.org/api/v3/``
Staging      ``https://addons.allizom.org/api/v3/``
Development  ``https://addons-dev.allizom.org/api/v3/``
===========  =========================================

Production
    Connect to this API for all normal operation.
Staging or Development
    Connect to these APIs if you need to work with a scratch database or
    you're testing features that aren't available in production yet.
    Your production account is not linked to any of these APIs.

Dive into the :ref:`authentication section <api-auth>` for an example of how to
get started using the API.

.. toctree::
   :maxdepth: 2

   common-responses
   auth
   accounts
   signing
   github
