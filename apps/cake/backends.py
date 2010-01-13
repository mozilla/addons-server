from time import time

from django.contrib.auth.models import User

import phpserialize

from users.models import UserProfile


class SessionBackend:

    def authenticate(self, session):
        """
        Given a CakeSession object we'll authenticate it to an actual user.
        """

        if (time() > session.expires or
            not session.data.startswith('User|')):
            session.delete()
            return None

        serialized_data = session.data[5:]

        php_user = phpserialize.loads(serialized_data)
        user_id = int(php_user.get('id'))

        try:
            profile = UserProfile.objects.get(pk=user_id)
        except UserProfile.DoesNotExist:
            session.delete()
            return None

        if profile.user is None:
            profile.create_django_user()

        return profile.user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
