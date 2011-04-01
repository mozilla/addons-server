from django.contrib.auth.models import User

from .models import UserProfile


class AmoUserBackend(object):
    supports_anonymous_user = False
    supports_object_permissions = False

    def authenticate(self, username=None, password=None):
        try:
            profile = UserProfile.objects.get(email=username)
            if profile.check_password(password):
                if profile.user_id is None:
                    profile.create_django_user()
                return profile.user
        except UserProfile.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class NoAuthForYou(object):
    """An authentication backend for read-only mode."""
    supports_anonymous_user = False
    supports_object_permissions = False

    def authenticate(self, *args, **kw):
        return None

    def get_user(self, *args, **kw):
        return None
