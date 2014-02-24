# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import json

from django.conf import settings
from django.core import mail
from django.db import models
from django.test.client import RequestFactory
from django.utils import translation

import phpserialize as php
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from stats.models import ClientData, Contribution
from stats.db import StatsDictField
from users.models import UserProfile
from zadmin.models import DownloadSource


class TestStatsDictField(amo.tests.TestCase):

    def test_to_python_none(self):
        eq_(StatsDictField().to_python(None), None)

    def test_to_python_dict(self):
        eq_(StatsDictField().to_python({'a': 1}), {'a': 1})

    def test_to_python_php(self):
        val = {'a': 1}
        eq_(StatsDictField().to_python(php.serialize(val)), val)

    def test_to_python_json(self):
        val = {'a': 1}
        eq_(StatsDictField().to_python(json.dumps(val)), val)


class TestContributionModel(amo.tests.TestCase):
    fixtures = ['stats/test_models.json']

    def setUp(self):
        user = UserProfile.objects.create(username='t@t.com')
        self.con = Contribution.objects.get(pk=1)
        self.con.update(type=amo.CONTRIB_PURCHASE, user=user)

    def test_related_protected(self):
        user = UserProfile.objects.create(username='foo@bar.com')
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        payment = Contribution.objects.create(user=user, addon=addon)
        Contribution.objects.create(user=user, addon=addon, related=payment)
        self.assertRaises(models.ProtectedError, payment.delete)

    def test_locale(self):
        translation.activate('en_US')
        eq_(Contribution.objects.all()[0].get_amount_locale(), u'$1.99')
        translation.activate('fr')
        eq_(Contribution.objects.all()[0].get_amount_locale(), u'1,99\xa0$US')


class TestEmail(amo.tests.TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.user = UserProfile.objects.get(pk=999)

    def make_contribution(self, amount, locale, type):
        return Contribution.objects.create(type=type, addon=self.addon,
                                           user=self.user, amount=amount,
                                           source_locale=locale)

    def test_thankyou_note(self):
        self.addon.enable_thankyou = True
        self.addon.thankyou_note = u'Thank "quoted". <script>'
        self.addon.name = u'Test'
        self.addon.save()
        cont = self.make_contribution('10', 'en-US', amo.CONTRIB_PURCHASE)
        cont.update(transaction_id='yo',
                    post_data={'payer_email': 'test@tester.com'})

        cont.mail_thankyou()
        eq_(len(mail.outbox), 1)
        email = mail.outbox[0]
        eq_(email.to, ['test@tester.com'])
        assert '&quot;' not in email.body
        assert u'Thank "quoted".' in email.body
        assert '<script>' not in email.body
        assert '&lt;script&gt;' not in email.body


class TestClientData(amo.tests.TestCase):

    def test_get_or_create(self):
        download_source = DownloadSource.objects.create(name='mkt-home')
        device_type = 'desktop'
        user_agent = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:16.0)'
        client = RequestFactory()
        request = client.post('/somewhere',
                              data={'src': download_source.name,
                                    'device_type': device_type,
                                    'is_chromeless': False},
                              **{'HTTP_USER_AGENT': user_agent})

        cli = ClientData.get_or_create(request)
        eq_(cli.download_source, download_source)
        eq_(cli.device_type, device_type)
        eq_(cli.user_agent, user_agent)
        eq_(cli.is_chromeless, False)
        eq_(cli.language, 'en-us')
        eq_(cli.region, None)
