from rest_framework.permissions import BasePermission


class AllowCollectionAuthor(BasePermission):

    def has_permission(self, request, view):
        return view.get_account_viewset().self_view

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
