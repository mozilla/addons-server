.. _acl:

====================
Access Control Lists
====================


ACL versus Django Permissions
-----------------------------

Currently we use the :attr:`~django.contrib.auth.models.User.is_superuser`
flag in the :class:`~django.contrib.auth.models.User` model to indicate that a
user can access the admin site.

Outside of that we use the :class:`~access.models.GroupUser` to define what
access groups a user is a part of.  We store this in ``request.groups``.


How permissions work
--------------------

Permissions that you can use as filters can be either explicit or general.

For example ``Admin:EditAddons`` means only someone with that permission will
validate.

If you simply require that a user has `some` permission in the `Admin` group
you can use ``Admin:%``.  The ``%`` means "any."

Similarly a user might be in a group that has explicit or general permissions.
They may have ``Admin:EditAddons`` which means they can see things with that
same permission, or things that require ``Admin:%``.

If a user has a wildcard, they will have more permissions.  For example,
``Admin:*`` means they have permission to see anything that begins with
``Admin:``.

The notion of a superuser has a permission of ``*:*`` and therefore they can
see everything.
