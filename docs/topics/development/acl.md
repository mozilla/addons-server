(acl)=

# Access Control Lists

## How permissions work

On top of that we use the `access.models.GroupUser` and `Group` to define
what access groups a user is a part of, and each group has `rules` defining
which permissions they grant their members, separated by `,`.

Permissions that you can use as filters can be either explicit or general.

For example `Admin:EditAddons` means only someone with that permission will
validate.

If you simply require that a user has _some_ permission in the _Admin_ group
you can use `Admin:%`.  The `%` means "any."

Similarly a user might be in a group that has explicit or general permissions.
They may have `Admin:EditAddons` which means they can see things with that
same permission, or things that require `Admin:%`.

If a user has a wildcard, they will have more permissions.  For example,
`Admin:*` means they have permission to see anything that begins with
`Admin:`.

The notion of a superuser has a permission of `*:*` and therefore they can
see everything.

## Django Admin

Django admin relies on 2 things to gate access:

- To access the admin itself, `UserProfile.is_staff` needs to be `True`. Our custom implementation allows access to users with a `@mozilla.com` email.
- To access individual modules/apps, `UserProfile.has_perm(perm, obj)` and `UserProfile.has_module_perms(app_label)` need to return `True`. Our custom implementation uses the `Group` of the current user as above, with a mapping constant called `DJANGO_PERMISSIONS_MAPPING` which translates Django-style permissions into our own.
