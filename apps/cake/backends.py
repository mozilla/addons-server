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
            # reusing the id will make our life easier, because we can use the
            # OneToOneField as pk for Profile linked back to the auth.user
            # in the future
            profile.user = User(id=profile.pk)
            profile.user.first_name  = profile.firstname
            profile.user.last_name   = profile.lastname
            profile.user.username    = profile.nickname
            profile.user.email       = profile.email
            profile.user.password    = profile.password
            profile.user.date_joined = profile.created
            profile.user.save()
            profile.save()

        return profile.user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
