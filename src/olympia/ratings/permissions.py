from rest_framework.permissions import BasePermission

from olympia import amo
from olympia.access import acl


def user_can_delete_rating(request, rating):
    """Return whether or not the request.user can delete a rating.

    People who can delete ratings:
      * The original rating author.
      * Reviewers with Ratings:Moderate, if the rating has been flagged and
        they are not an author of this add-on.
      * Users in a group with "Users:Edit" or "Addons:Edit" privileges and
        they are not an author of this add-on.
    """
    is_rating_author = (
        request.user.is_authenticated and rating.user_id == request.user.id)
    is_addon_author = rating.addon.has_author(request.user)
    is_moderator = (
        acl.action_allowed(request, amo.permissions.RATINGS_MODERATE) and
        rating.editorreview
    )
    can_edit_users_or_addons = (
        acl.action_allowed(request, amo.permissions.USERS_EDIT) or
        acl.action_allowed(request, amo.permissions.ADDONS_EDIT)
    )

    return (
        is_rating_author or
        (not is_addon_author and (is_moderator or can_edit_users_or_addons))
    )


def user_can_vote_rating(request, rating):
    """Return whether or not the request.user can vote for a rating.

    People who can vote for ratings:
      * Not the original rating author.
      * Not the original add-on author.
    """
    is_rating_author = (
        request.user.is_authenticated and rating.user_id == request.user.id)
    is_addon_author = rating.addon.has_author(request.user)

    return (
        (not is_rating_author) and
        (not is_addon_author)
    )




class CanDeleteRatingPermission(BasePermission):
    """A DRF permission class wrapping user_can_delete_rating()."""
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return user_can_delete_rating(request, obj)


class CanVotePermission(BasePermission):
    """A DRF permission class wrapping user_can_vote_rating()."""
    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return user_can_vote_rating(request, obj)
