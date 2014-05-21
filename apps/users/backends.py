from .models import UserProfile, RequestUser


class AmoUserBackend(object):
    supports_anonymous_user = False
    supports_inactive_user = False
    supports_object_permissions = False

    def authenticate(self, username=None, password=None):
        try:
            profile = UserProfile.objects.get(email=username)
            if profile.check_password(password):
                return profile
        except UserProfile.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return RequestUser.objects.get(pk=user_id)
        except RequestUser.DoesNotExist:
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
