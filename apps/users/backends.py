from django.contrib.auth.models import User

from .models import UserProfile


class AmoUserBackend(object):

    def authenticate(self, username=None, password=None):
        try:
            profile = UserProfile.objects.get(email=username)
            if profile.check_password(password):
                if profile.user is None:
                    profile.create_django_user()
                return profile.user
        except UserProfile.DoesNotExist:
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
