from django import test
from django.conf import settings
from django.core import mail

from nose.tools import eq_

from amo.utils import send_mail


class SendMailTest(test.TestCase):

    def setUp(self):
        self._email_blacklist = list(getattr(settings, 'EMAIL_BLACKLIST', []))

    def tearDown(self):
        settings.EMAIL_BLACKLIST = self._email_blacklist

    def test_blacklist(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_BLACKLIST = (to,)
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False)

        assert success
        eq_(len(mail.outbox), 0)

    def test_blacklist_flag(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_BLACKLIST = (to,)
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False,
                            use_blacklist=True)
        assert success
        eq_(len(mail.outbox), 0)

        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False,
                            use_blacklist=False)
        assert success
        eq_(len(mail.outbox), 1)

    def test_success(self):
        to = 'nobody@mozilla.org'
        settings.EMAIL_BLACKLIST = ()
        success = send_mail('test subject', 'test body',
                            recipient_list=[to], fail_silently=False)

        assert success
        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].subject.find('test subject') == 0
        assert mail.outbox[0].body.find('test body') == 0

