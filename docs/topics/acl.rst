.. _acl:

====================
Access Control Lists
====================

.. automodule:: access


ACL versus Django Permissions
-----------------------------

Currently we use the :attr:`~django.contrib.auth.models.User.is_superuser`
flag in the :class:`~django.contrib.auth.models.User` model to indicate that a
user can access the admin site.

Outside of that we use the :class:`~access.models.GroupUser` to define what
access groups a user is a part of.  We store this in ``request.groups``.
