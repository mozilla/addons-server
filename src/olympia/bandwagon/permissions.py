from django.conf import settings

from rest_framework.permissions import BasePermission

from olympia import amo
from olympia.access import acl


class AllowCollectionAuthor(BasePermission):

    def has_permission(self, request, view):
        return view.get_account_viewset().self_view

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class AllowCollectionContributor(BasePermission):
    """Allow people with the collections contribute permission to modify the
    featured themes collection.  Be careful where this used as it can allow
    creating / listing objects if used alone in a ViewSet that has those
    actions."""

    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return (
            obj and
            obj.pk == settings.COLLECTION_FEATURED_THEMES_ID and
            acl.action_allowed(request, amo.permissions.COLLECTIONS_CONTRIBUTE)
        )
