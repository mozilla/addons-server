from rest_framework.permissions import BasePermission


class AllowCollectionAuthor(BasePermission):

    def has_permission(self, request, view):
        return view.get_account_viewset().self_view

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class AllowCollectionContributor(BasePermission):
    """Allow a contributor of a collection to do stuff.  Be careful how this
    is used - """

    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return obj in request.user.collections_publishable.all()
