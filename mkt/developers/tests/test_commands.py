# -*- coding: utf-8 -*-
from django.core import mail
from django.core.management.base import CommandError

from nose.tools import eq_, raises

import amo
import amo.tests
from addons.models import Addon, AddonPremium
from mkt.developers.management.commands import (cleanup_addon_premium,
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

    def test_email_developers_locale(self):
        app = Webapp.objects.get(id=337141)
        app.update(premium_type=amo.ADDON_PREMIUM)
        author = app.authors.all()[0]
        eq_(author.lang, None)
        email_developers_about_new_paid_region.Command().handle('uk')
        msg = mail.outbox[0]
        eq_(msg.subject,
            (u'Something Something Steamcube!: United Kingdom region added '
             u'to the Firefox Marketplace'))
        assert 'payments for United Kingdom' in msg.body
        assert 'your app, Something Something Steamcube!' in msg.body

        mail.outbox = []
        author.update(lang=u'es')
        email_developers_about_new_paid_region.Command().handle('uk')
        msg = mail.outbox[0]
        eq_(msg.subject,
            (u'Algo Algo Steamcube!: Reino Unido región agregada a '
             u'Firefox Marketplace'))
        assert u'pagos para Reino Unido' in msg.body
        assert u'tu aplicación Algo Algo Steamcube!' in msg.body

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


class TestCommandViews(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = self.get_webapp()

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_cleanup_addonpremium(self):
        self.make_premium(self.webapp)
        eq_(AddonPremium.objects.all().count(), 1)
        cleanup_addon_premium.Command().handle()
        eq_(AddonPremium.objects.all().count(), 1)
        self.webapp.update(premium_type=amo.ADDON_FREE)
        cleanup_addon_premium.Command().handle()
        eq_(AddonPremium.objects.all().count(), 0)
