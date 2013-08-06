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
            (u'Algo Algo Steamcube!: Reino Unido region added '
             u'to the Firefox Marketplace'))
        assert 'payments for Reino Unido' in msg.body
        assert 'your app, Algo Algo Steamcube!' in msg.body

    def test_email_developers_about_new_paid_region_without_premium(self):
        Webapp.objects.get(id=337141).update(premium_type=amo.ADDON_FREE)
        email_developers_about_new_paid_region.Command().handle('uk')
        eq_(len(mail.outbox), 0)

    def test_email_developers_about_new_paid_region_without_public(self):
        Webapp.objects.get(id=337141).update(status=amo.STATUS_NOMINATED)
        email_developers_about_new_paid_region.Command().handle('uk')
        eq_(len(mail.outbox), 0)

    @raises(CommandError)
    def test_email_developers_about_new_paid_region_without_region(self):
        email_developers_about_new_paid_region.Command().handle()
