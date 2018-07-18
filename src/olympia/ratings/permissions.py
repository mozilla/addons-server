from rest_framework.permissions import BasePermission

from olympia.ratings.templatetags.jinja_helpers import user_can_delete_review


class CanDeleteRatingPermission(BasePermission):
    """A DRF permission class wrapping user_can_delete_review()."""

    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return user_can_delete_review(request, obj)
