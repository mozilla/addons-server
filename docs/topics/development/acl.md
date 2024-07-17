(acl)=

# Access Control Lists

## How permissions work

On top of that we use the _access.models.GroupUser_ and _Group_ to define
what access groups a user is a part of, and each group has _rules_ defining
which permissions they grant their members, separated by `,`.

Permissions that you can use as filters can be either explicit or general.

For example _Admin:EditAddons_ means only someone with that permission will
validate.

If you simply require that a user has _some_ permission in the _Admin_ group
you can use `Admin:%`.  The _%_ means "any."

Similarly a user might be in a group that has explicit or general permissions.
They may have _Admin:EditAddons_ which means they can see things with that
same permission, or things that require `Admin:%`.

If a user has a wildcard, they will have more permissions.  For example,
_Admin:*_ means they have permission to see anything that begins with
`Admin:`.

The notion of a superuser has a permission of _*:*_ and therefore they can
see everything.

## Django Admin

Django admin relies on 2 things to gate access:

- To access the admin itself, _UserProfile.is_staff_ needs to be `True`. Our custom implementation allows access to users with a _@mozilla.com_ email.
- To access individual modules/apps, _UserProfile.has_perm(perm, obj)_ and _UserProfile.has_module_perms(app_label)_ need to return `True`. Our custom implementation uses the _Group_ of the current user as above, with a mapping constant called _DJANGO_PERMISSIONS_MAPPING_ which translates Django-style permissions into our own.
