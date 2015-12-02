from django.conf import settings
from django.core import mail

from nose.tools import eq_

import amo.tests
from abuse.models import AbuseReport


class TestAbuse(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/user_999']

    def test_user(self):
        AbuseReport(user_id=999).send()
        assert mail.outbox[0].subject.startswith('[User]')
        eq_(mail.outbox[0].to, [settings.ABUSE_EMAIL])

    def test_addon(self):
        AbuseReport(addon_id=3615).send()
        assert mail.outbox[0].subject.startswith('[Extension]')

    def test_addon_fr(self):
        with self.activate(locale='fr'):
            AbuseReport(addon_id=3615).send()
        assert mail.outbox[0].subject.startswith('[Extension]')
