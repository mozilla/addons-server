from time import time

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils.encoding import smart_str

import commonware.log
import phpserialize

from users.models import UserProfile

log = commonware.log.getLogger('z.cake')


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
            serialized_data = smart_str(session.data[5:])
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

        def retrieve_from_master(pk):
            return UserProfile.objects.using('default').no_cache().get(pk=pk)

        # User will hit this if they are new to zamboni.
        try:
            if profile.user is None:
                # This will catch replication lags in case we created a user.
                profile = retrieve_from_master(user_id)
                if profile.user is None:
                    profile.create_django_user()
        except User.DoesNotExist:
            log.warning('Bad user_id {0} on UserProfile {1}.'.format(
                    profile.id, profile.user_id))
            # Chances are we are suffering from replication lag, but
            # let's play it safe and just not authenticate.
            return None
        except IntegrityError, e:
            # Typically a duplicate key.
            log.warning('DB Error for UserProfile {0}: {1}'.format(user_id, e))
            return None

        except Exception, e:
            log.error('Unknown exception for UserProfile {0}: {1}'.format(
                    user_id, e))
            return None

        return profile.user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
