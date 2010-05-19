import base64
import hashlib
import time

from django.conf import settings

import commonware.log

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
        key = settings.SECRET_KEY
        return hashlib.sha256("%s%s" % (token, key)).hexdigest()
