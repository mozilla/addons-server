from django.core import mail
from django.core.management.base import CommandError

from nose.tools import eq_, raises

import amo
import amo.tests
from mkt.developers.management.commands import (
    email_developers_about_new_paid_region)
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestCommand(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def test_email_developers_about_new_paid_region(self):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM)
        email_developers_about_new_paid_region.Command().handle('uk')
        msg = mail.outbox[0]
        eq_(msg.subject,
            '%s: United Kingdom region added to the Firefox Marketplace'
            % app.name)

    def test_email_developers_about_new_paid_region_with_pending_status(self):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM, status=amo.STATUS_PENDING)
        email_developers_about_new_paid_region.Command().handle('uk')
        msg = mail.outbox[0]
        eq_(msg.subject,
            '%s: United Kingdom region added to the Firefox Marketplace'
            % app.name)

    def test_email_developers_about_new_paid_region_without_premium(self):
        Webapp.objects.get(id=337141).update(premium_type=amo.ADDON_FREE)
        email_developers_about_new_paid_region.Command().handle('uk')
        eq_(len(mail.outbox), 0)

    def test_email_developers_about_new_paid_region_with_rejected_status(self):
        Webapp.objects.get(id=337141).update(premium_type=amo.ADDON_PREMIUM,
                                             status=amo.STATUS_REJECTED)
        email_developers_about_new_paid_region.Command().handle('uk')
        eq_(len(mail.outbox), 0)

    @raises(CommandError)
    def test_email_developers_about_new_paid_region_without_region(self):
        email_developers_about_new_paid_region.Command().handle()
