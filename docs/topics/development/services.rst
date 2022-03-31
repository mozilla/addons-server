.. _services:

==========================
Services
==========================

The services directory contain a special separate piece of code that deals with the update service Firefox calls to get updates about installed add-ons (though the ``extensions.update.background.url`` and ``extensions.update.background.url`` preferences).

In dev/stage/prod, this would have its own domain, but locally, we re-use the same as
the rest of addons-server, and our nginx configuration answers using the separate ``versioncheck`` wsgi service for all requests with a /update/ prefix as their path. This minimal configuration has autoreload disabled to stay as lean as possible, so to you'll need to manually restart the web docker service to see changes.

A typical URL to test with would look like this: ``http://olympia.test/update/?reqVersion=1&id=addon@guid&version=0.1&appID={ec8030f7-c20a-464f-9b0e-13a3a9e97384}&appVersion=99.0``
