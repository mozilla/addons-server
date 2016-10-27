.. _third-party:

=================
Third-Party Usage
=================

Running your own Add-ons server will likely require a few changes. There is currently no easy
way to provide custom templates and since Firefox Accounts is used for authentication there is
no way to authenticate a user outside of a Mozilla property.

If you would like to run your own Add-ons server you may want to update addons-server to support
custom templates and move the Firefox Accounts management to a `django authentication backend`_.

Another option would be to add any APIs that you required and write a custom frontend. This work is
already underway and should be completed at some point but help is always welcome. You can find
the API work in this project and the frontend work in `addons-frontend`_.

.. _django authentication backend: https://github.com/mozilla/addons-server/issues/3799
.. _addons-frontend: https://github.com/mozilla/addons-frontend
