# -*- coding: utf-8 -*-
from django.core import mail

from olympia.amo.tests import TestCase
from olympia.addons.models import Addon
from olympia.stats.models import Contribution
from olympia.users.models import UserProfile


class TestEmail(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestEmail, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)

    def make_contribution(self, amount, locale):
        return Contribution.objects.create(addon=self.addon, amount=amount,
                                           source_locale=locale)

    def test_thankyou_note(self):
        self.addon.enable_thankyou = True
        self.addon.thankyou_note = u'Thank "quoted". <script>'
        self.addon.name = u'Test'
        self.addon.save()
        cont = self.make_contribution('10', 'en-US')
        cont.update(transaction_id='yo',
                    post_data={'payer_email': 'test@tester.com'})

        cont.mail_thankyou()
        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == ['test@tester.com']
        assert '&quot;' not in email.body
        assert u'Thank "quoted".' in email.body
        assert '<script>' not in email.body
        assert '&lt;script&gt;' not in email.body
