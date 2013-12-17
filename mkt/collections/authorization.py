from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

import commonware.log
from rest_framework.permissions import BasePermission

from access import acl

log = commonware.log.getLogger('mkt.collections')


class CuratorAuthorization(BasePermission):
    """
    Permission class governing ability to interact with Collection-related APIs.

    Rules:
    - All users may make GET requests.
    - Users with Collections:Curate may make any request.
    - Users in Collection().curators may make any request using a verb in the
      curator_verbs property.

    Note: rest-framework does not allow for situations where a user fails
        has_permission but passes has_object_permission, so the logic
        determining whether a user is a curator or has the Collections:Curate
        permission is abstracted from those methods and situationally called in
        each.
    """
    allow_public_get_requests = True
    curator_verbs = ['POST', 'PUT', 'PATCH']

    def is_public_get_request(self, request):
        return self.allow_public_get_requests and request.method == 'GET'

    def is_curator_for(self, request, obj):
        if isinstance(request.user, AnonymousUser):
            return False
        return (obj.has_curator(request.user.get_profile()) and request.method
                in self.curator_verbs)

    def has_curate_permission(self, request):
        return acl.action_allowed(request, 'Collections', 'Curate')

    def has_permission(self, request, view):
        if self.is_public_get_request(request):
            return True

        try:
            obj = view.get_object()
        except ImproperlyConfigured:
            # i.e. We're calling get_object from a non-object view.
            return self.has_curate_permission(request)
        else:
            return (self.has_curate_permission(request) or
                    self.is_curator_for(request, obj))

    def has_object_permission(self, request, view, obj):
        if (self.is_public_get_request(request) or
            self.has_curate_permission(request)):
            return True
        return self.is_curator_for(request, obj)


class StrictCuratorAuthorization(CuratorAuthorization):
    """
    The same as CuratorAuthorization, with GET requests for unauthorized users
    disallowed.
    """
    allow_public_get_requests = False
    curator_verbs = CuratorAuthorization.curator_verbs + ['GET']


class CanBeHeroAuthorization(BasePermission):
    """
    Only users with Collections:Curate can modify the can_be_hero field.
    """
    def has_curate_permission(self, request):
        return CuratorAuthorization().has_curate_permission(request)

    def is_modifying_request(self, request):
        return request.method in ('PUT', 'PATCH', 'POST',)

    def hero_field_modified(self, request):
        if request.method == 'POST' and 'can_be_hero' in request.POST:
            return True
        elif request.method in ('PATCH', 'POST', 'PUT'):
            return 'can_be_hero' in request.DATA.keys()
        return False

    def has_object_permission(self, request, view, obj):
        """
        Returns false if the request is attempting to modify the can_be_hero
        field and the authenticating use does not have the Collections:Curate
        permission.
        """
        return not (not self.has_curate_permission(request) and
                    self.is_modifying_request(request) and
                    self.hero_field_modified(request))
