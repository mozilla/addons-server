import itertools
import logging

from django.conf import settings
from django.core import mail
from django.core.management.base import BaseCommand

log = logging.getLogger('z.mailer')
FROM = settings.DEFAULT_FROM_EMAIL


class Command(BaseCommand):
    args = 'FILE [no really]'
    help = 'Send a message to everyone in FILE'

    def handle(self, filename, *args, **kw):
        backend = None
        if ' '.join(args[1:]) != 'no really':
            backend = 'django.core.mail.backends.console.EmailBackend'
        log.info('Using email backend: %r' % (backend or 'default'))
        cxn = mail.get_connection(backend=backend)
        sendmail(filename, cxn)


def sendmail(filename, cxn):
    counter = itertools.count()
    emails = [r.strip() for r in open(filename).readlines() if r.strip()]
    log.info('There are %d emails to send.' % len(emails))
    for email in emails:
        try:
            mail.send_mail(SUBJECT, MSG, FROM, [email], connection=cxn)
            log.info('%s. DONE: %s' % (counter.next(), email))
        except Exception, e:
            log.info('%s. FAIL: %s (%s)' % (counter.next(), email, e))


SUBJECT = 'Important notice about your addons.mozilla.org account'
MSG = """\
Dear addons.mozilla.org user,

The purpose of this email is to notify you about a possible disclosure
of your information which occurred on December 17th. On this date, we
were informed by a 3rd party who discovered a file with individual user
records on a public portion of one of our servers. We immediately took
the file off the server and investigated all downloads. We have
identified all the downloads and with the exception of the 3rd party,
who reported this issue, the file has been download by only Mozilla
staff.  This file was placed on this server by mistake and was a partial
representation of the users database from addons.mozilla.org. The file
included email addresses, first and last names, and an md5 hash
representation of your password. The reason we are disclosing this event
is because we have removed your existing password from the addons site
and are asking you to reset it by going back to the addons site and
clicking forgot password. We are also asking you to change your password
on other sites in which you use the same password. Since we have
effectively erased your password, you don't need to do anything if you
do not want to use your account.  It is disabled until you perform the
password recovery.

We have identified the process which allowed this file to be posted
publicly and have taken steps to prevent this in the future. We are also
evaluating other processes to ensure your information is safe and secure.

Should you have any questions, please feel free to contact the
infrastructure security team directly at infrasec@mozilla.com. If you
are having issues resetting your account, please contact
amo-admins@mozilla.org.

We apologize for any inconvenience this has caused.

Chris Lyon
Director of Infrastructure Security
"""
