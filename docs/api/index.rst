.. _api:

=======================
Firefox Marketplace API
=======================


About
=====

This documentation covers interacting with the `Firefox Marketplace`_.

.. toctree::
   :hidden:
   :maxdepth: 2

   topics/overview.rst
   topics/authentication.rst
   topics/abuse.rst
   topics/accounts.rst
   topics/apps.rst
   topics/comm.rst
   topics/export.rst
   topics/features.rst
   topics/feed.rst
   topics/fireplace.rst
   topics/payment.rst
   topics/ratings.rst
   topics/reviewers.rst
   topics/rocketfuel.rst
   topics/search.rst
   topics/site.rst
   topics/stats.rst
   topics/submission.rst
   topics/transactions.rst


Quickstart
==========

Details on an app: https://marketplace.firefox.com/api/v1/apps/app/twitter/?format=JSON

Search for all hosted apps about Twitter: https://marketplace.firefox.com/api/v1/apps/search/?q=twitter&app_type=hosted&format=JSON

Questions
=========

Contact us in the #marketplace-api channel on irc.mozilla.org.

Bugs or feature requests are filed in `Bugzilla`_. The code for the API
and the source of these docs is part of the `zamboni project`_.

.. _`Firefox Marketplace`: https://marketplace.firefox.com
.. _`Bugzilla`: https://bugzilla.mozilla.org/buglist.cgi?list_id=6405232&resolution=---&resolution=DUPLICATE&query_format=advanced&component=API&product=Marketplace
.. _`zamboni project`: https://github.com/mozilla/zamboni
