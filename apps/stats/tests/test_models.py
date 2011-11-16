# -*- coding: utf-8 -*-
import json

from django.core import mail
from django.db import models
from django.utils import translation

import phpserialize as php
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from stats.models import Contribution
from stats.db import StatsDictField
from users.models import UserProfile


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

    def chargeback_email(self, amount, locale):
        cont = Contribution.objects.create(type=amo.CONTRIB_CHARGEBACK,
                                           addon=self.addon, user=self.user,
                                           amount=amount,
                                           source_locale=locale)
        cont.mail_chargeback()
        eq_(len(mail.outbox), 1)
        return mail.outbox[0]

    def test_chargeback_email(self):
        email = self.chargeback_email('10', 'en-US')
        eq_(email.subject, u'%s payment reversal' % self.addon.name)
        assert str(self.addon.name) in email.body

    def test_chargeback_negative(self):
        email = self.chargeback_email('-10', 'en-US')
        assert '$10.00' in email.body

    def test_chargeback_positive(self):
        email = self.chargeback_email('10', 'en-US')
        assert '$10.00' in email.body

    def test_chargeback_unicode(self):
        self.addon.name = u'Азәрбајҹан'
        self.addon.save()
        email = self.chargeback_email('-10', 'en-US')
        assert '$10.00' in email.body

    def test_chargeback_locale(self):
        self.addon.name = {'fr':u'België'}
        self.addon.locale = 'fr'
        self.addon.save()
        email = self.chargeback_email('-10', 'fr')
        assert u'België' in email.body
        assert u'10,00\xa0$US' in email.body
