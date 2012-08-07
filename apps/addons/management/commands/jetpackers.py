import logging

from django.core import mail
from django.conf import settings
from django.core.management.base import BaseCommand

import amo.utils
from users.models import UserProfile

log = logging.getLogger('z.mailer')
FROM = settings.DEFAULT_FROM_EMAIL


class Command(BaseCommand):
    help = "Send the email for bug 662571"

    def handle(self, *args, **options):
        sendmail()


def sendmail():
    addrs = set(UserProfile.objects.values_list('email', flat=True)
                # whoa
                .filter(addons__versions__files__jetpack_version__isnull=False))
    log.info('There are %d emails to send.' % len(addrs))
    count = 0
    for addr in addrs:
        count += 1
        try:
            mail.send_mail(SUBJECT, MSG, FROM, [addr])
            log.info('%s. DONE: %s' % (count, addr))
        except Exception, e:
            log.info('%s. FAIL: %s (%s)' % (count, addr, e))


SUBJECT = 'Instructions for Automatic Upgrade to Add-on SDK 1.0'
MSG = """\
Hello Mozilla Add-ons Developer!

With the final version of the Add-on SDK only a week away, we wanted to
get in touch with all add-on developers who have existing SDK-based
(Jetpack) add-ons.  We would like you to know that going forward AMO
will be auto-updating add-ons with new versions of the Add-on SDK upon
release.

To  ensure that your add-on(s) are auto-updated with the 1.0 final
version of the SDK, we would ask that you download the latest release
candidate build -
https://ftp.mozilla.org/pub/mozilla.org/labs/jetpack/addon-sdk-1.0rc2.tar.gz,
https://ftp.mozilla.org/pub/mozilla.org/labs/jetpack/addon-sdk-1.0rc2.zip
- and update your add-on(s) on AMO. After the 1.0 release, we will scan
our add-ons database and automatically upgrade any SDK-based add-ons we
find that are using verions 1.0RC2 or greater to the 1.0 final version
of the SDK. Any add-ons we find using  versions of the SDK below 1.0RC2
will not be auto-updated and you will need to upgrade them to the 1.0
version of the SDK manually.

Thank you for participating in the early stages of the Add-on SDK's
development. Feedback and engagement from developers like you are the
foundations for success in our open source community!

Sincerely,
The Mozilla Add-ons Team
"""
