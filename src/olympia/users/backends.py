from django.db.models import Q

from .models import UserProfile


class TestUserBackend(object):
    """Authentication backend to easily log in a user while testing."""

    def authenticate(self, username=None, email=None, password=None):
        # This needs to explicitly throw when there is a password since django
        # will skip this backend if a user passes a password.
        # http://bit.ly/2duYr93
        if password is not None:
            raise TypeError('password is not allowed')
        try:
            return UserProfile.objects.get(
                Q(email=email) | Q(username=username)
            )
        except UserProfile.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return UserProfile.objects.get(pk=user_id)
        except UserProfile.DoesNotExist:
            return None


class NoAuthForYou(object):
    """An authentication backend for read-only mode."""

    supports_anonymous_user = False
    supports_inactive_user = False
    supports_object_permissions = False

    def authenticate(self, *args, **kw):
        return None

    def get_user(self, *args, **kw):
        return None
