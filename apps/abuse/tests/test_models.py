from django.conf import settings
from django.core import mail

from nose.tools import eq_

import amo
import amo.tests
from abuse.models import AbuseReport


class TestAbuse(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def test_user(self):
        abuse = AbuseReport.objects.create(user_id=999)
        abuse.send()
        assert mail.outbox[0].subject.startswith('[User]')
        eq_(mail.outbox[0].to, [settings.ABUSE_EMAIL])

    def test_addon(self):
        abuse = AbuseReport.objects.create(addon_id=3615)
        abuse.send()
        assert mail.outbox[0].subject.startswith('[Extension]')

    def test_addon_fr(self):
        abuse = AbuseReport.objects.create(addon_id=3615)
        with self.activate(locale='fr'):
            abuse.send()
        assert mail.outbox[0].subject.startswith('[Extension]')
