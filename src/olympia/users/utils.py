import base64
from functools import partial
import hashlib
import hmac
import time
import uuid

from django.conf import settings
from django.db.models import Q

import commonware.log

from olympia.users.models import UserProfile, BlacklistedName

log = commonware.log.getLogger('z.users')


class EmailResetCode():

    @classmethod
    def create(cls, user_id, email):
        """Encode+Hash an email for a reset code.  This is the new email."""
        data = [user_id, email]
        data.append(int(time.time()))

        token = ",".join([str(i) for i in data])
        secret = cls.make_secret(token)

        return base64.urlsafe_b64encode(token), secret

    @classmethod
    def parse(cls, code, hash):
        """Extract a user id and an email from a code and validate against a
        hash.  The hash ensures us the email address hasn't changed and that
        the email address matches the user id.  This will raise
        ``ValueError`` if the hash fails or if the code is over 48 hours
        old."""
        try:
            decoded = base64.urlsafe_b64decode(str(code))
            user_id, mail, req_time = decoded.split(',')
        except (ValueError, TypeError):
            # Data is broken
            raise ValueError

        if cls.make_secret(decoded) != hash:
            log.info(u"[Tampering] Email reset data does not match hash")
            raise ValueError

        # Is the request over 48 hours old?
        age = time.time() - int(req_time)
        if age > 48 * 60 * 60:
            raise ValueError

        return int(user_id), mail

    @classmethod
    def make_secret(cls, token):
        return hmac.new(settings.SECRET_KEY, msg=token,
                        digestmod=hashlib.sha256).hexdigest()


class UnsubscribeCode():

    @classmethod
    def create(cls, email):
        """Encode+Hash an email for an unsubscribe code."""
        secret = cls.make_secret(email)
        return base64.urlsafe_b64encode(email), secret

    @classmethod
    def parse(cls, code, hash):
        try:
            decoded = base64.urlsafe_b64decode(str(code))
            mail = decoded
        except (ValueError, TypeError):
            # Data is broken
            raise ValueError

        if cls.make_secret(decoded) != hash:
            log.info(u"[Tampering] Unsubscribe link data does not match hash")
            raise ValueError

        return mail

    @classmethod
    def make_secret(cls, token):
        return hmac.new(settings.SECRET_KEY, msg=token,
                        digestmod=hashlib.sha256).hexdigest()


def get_task_user():
    """
    Returns a user object. This user is suitable for assigning to
    cron jobs or long running tasks.
    """
    return UserProfile.objects.get(pk=settings.TASK_USER_ID)


def find_users(email):
    """
    Given an email find all the possible users, by looking in
    users and in their history.
    """
    return UserProfile.objects.filter(Q(email=email) |
                                      Q(history__email=email)).distinct()


def autocreate_username(candidate, tries=1):
    """Returns a unique valid username."""
    max_tries = settings.MAX_GEN_USERNAME_TRIES
    from olympia.amo.utils import slugify, SLUG_OK
    make_u = partial(slugify, ok=SLUG_OK, lower=True, spaces=False,
                     delimiter='-')
    adjusted_u = make_u(candidate)
    if tries > 1:
        adjusted_u = '%s%s' % (adjusted_u, tries)
    if (BlacklistedName.blocked(adjusted_u) or adjusted_u == '' or
            tries > max_tries or len(adjusted_u) > 255):
        log.info('username blocked, empty, max tries reached, or too long;'
                 ' username=%s; max=%s' % (adjusted_u, max_tries))
        return autocreate_username(uuid.uuid4().hex[0:15])
    if UserProfile.objects.filter(username=adjusted_u).count():
        return autocreate_username(candidate, tries=tries + 1)
    return adjusted_u
