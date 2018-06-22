import base64
import hashlib
import hmac
import uuid

from functools import partial

from django.conf import settings
from django.db.models import Q
from django.utils.encoding import force_bytes

import olympia.core.logger

from olympia import amo
from olympia.users.models import DeniedName, UserProfile


class UnsubscribeCode(object):

    @classmethod
    def create(cls, email):
        """Encode+Hash an email for an unsubscribe code."""
        # Need to make sure email is in bytes to make b64encoding and hmac.new
        # work.
        email = force_bytes(email)
        secret = cls.make_secret(email)
        return base64.urlsafe_b64encode(email), secret

    @classmethod
    def parse(cls, code, hash):
        try:
            decoded = base64.urlsafe_b64decode(str(code))
            email = decoded
        except (ValueError, TypeError):
            # Data is broken
            raise ValueError

        if cls.make_secret(decoded) != hash:
            log.info(u"[Tampering] Unsubscribe link data does not match hash")
            raise ValueError

        return email

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
    if (DeniedName.blocked(adjusted_u) or adjusted_u == '' or
            tries > max_tries or len(adjusted_u) > 255):
        log.info('username blocked, empty, max tries reached, or too long;'
                 ' username=%s; max=%s' % (adjusted_u, max_tries))
        return autocreate_username(uuid.uuid4().hex[0:15])
    if UserProfile.objects.filter(username=adjusted_u).count():
        return autocreate_username(candidate, tries=tries + 1)
    return adjusted_u


def system_addon_submission_allowed(user, parsed_addon_data):
    guid = parsed_addon_data.get('guid') or ''
    return (
        not guid.endswith(amo.SYSTEM_ADDON_GUIDS) or
        user.email.endswith(u'@mozilla.com'))


def mozilla_signed_extension_submission_allowed(user, parsed_addon_data):
    return (
        not parsed_addon_data.get('is_mozilla_signed_extension') or
        user.email.endswith(u'@mozilla.com'))
