import base64
import hashlib
import hmac

from django.conf import settings
from django.utils.encoding import force_bytes, force_text

import olympia.core.logger

from olympia import amo
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.users')


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
            decoded = base64.urlsafe_b64decode(force_bytes(code))
            email = decoded
        except (ValueError, TypeError):
            # Data is broken
            raise ValueError

        if cls.make_secret(decoded) != hash:
            log.info(u'[Tampering] Unsubscribe link data does not match hash')
            raise ValueError

        return force_text(email)

    @classmethod
    def make_secret(cls, token):
        return hmac.new(force_bytes(settings.SECRET_KEY), msg=token,
                        digestmod=hashlib.sha256).hexdigest()


def get_task_user():
    """
    Returns a user object. This user is suitable for assigning to
    cron jobs or long running tasks.
    """
    return UserProfile.objects.get(pk=settings.TASK_USER_ID)


def system_addon_submission_allowed(user, parsed_addon_data):
    guid = parsed_addon_data.get('guid') or ''
    return (
        not guid.lower().endswith(amo.SYSTEM_ADDON_GUIDS) or
        user.email.endswith(u'@mozilla.com'))


def mozilla_signed_extension_submission_allowed(user, parsed_addon_data):
    return (
        not parsed_addon_data.get('is_mozilla_signed_extension') or
        user.email.endswith(u'@mozilla.com'))
