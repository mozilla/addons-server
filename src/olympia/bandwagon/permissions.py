from rest_framework.permissions import BasePermission


class AllowCollectionAuthor(BasePermission):

    def has_permission(self, request, view):
        return view.get_account_viewset().self_view

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class AllowNonListActions(BasePermission):

    def has_permission(self, request, view):
        return getattr(view, 'action', '') != 'list'

    def has_object_permission(self, request, view, obj):
        return True


class AllowListedCollectionOnly(BasePermission):

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        # Anyone can access a collection if they know the slug, if it's listed.
        return obj.listed
