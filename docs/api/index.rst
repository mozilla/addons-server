.. _api:

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


=======================
Firefox Marketplace API
=======================

This documentation covers APIs related to the `Firefox Marketplace`_.


Quickstart
==========

Details on an app: https://marketplace.firefox.com/api/v1/apps/app/twitter/?format=JSON

Search for all hosted apps about Twitter: https://marketplace.firefox.com/api/v1/apps/search/?q=twitter&app_type=hosted&format=JSON


Questions
=========

Updates and changes are announced on the `marketplace-api-announce`_ mailing
list. We recommended that all API consumers subscribe.

Questions or concerns may be raised in the #marketplace channel on
irc.mozilla.org.

Bugs or feature requests are filed in `Bugzilla`_. The code for the API
and the source of these docs is part of the `zamboni project`_.

.. _`Firefox Marketplace`: https://marketplace.firefox.com
.. _`marketplace-api-announce`: https://mail.mozilla.org/listinfo/marketplace-api-announce
.. _`Bugzilla`: https://bugzilla.mozilla.org/buglist.cgi?list_id=6405232&resolution=---&resolution=DUPLICATE&query_format=advanced&component=API&product=Marketplace
.. _`zamboni project`: https://github.com/mozilla/zamboni