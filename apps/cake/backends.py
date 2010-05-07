import logging
from time import time

from django.contrib.auth.models import User

import phpserialize

from users.models import UserProfile

log = logging.getLogger('z.cake')


class SessionBackend:

    def authenticate(self, session):
        """
        Given a CakeSession object we'll authenticate it to an actual user.
        """

        if (time() > session.expires or
            not session.data.startswith('User|')):
            session.delete()
            return None

        try:
            serialized_data = session.data[5:]
            php_user = phpserialize.loads(serialized_data)
        except ValueError, e:
            # Bug 553397
            log.warning("Found corrupt session (%s): %s" % (session.pk, e))
            session.delete()
            return None

        user_id = int(php_user.get('id'))

        try:
            profile = UserProfile.objects.get(pk=user_id)
        except UserProfile.DoesNotExist:
            session.delete()
            return None

        # User will hit this if they are new to zamboni.
        if profile.user is None:
            # This will catch replication lags in case we created a user.
            profile = UserProfile.objects.using('default').no_cache().get(
                    pk=user_id)
            if profile.user is None:
                profile.create_django_user()

        return profile.user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
