from datetime import datetime, timedelta

from django.core import mail

from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon, AddonUser
from market.cron import clean_out_addonpremium, mail_pending_refunds
from market.models import AddonPremium, Refund
from stats.models import Contribution
from users.models import UserProfile


class TestCronDeletes(amo.tests.TestCase):

    def setUp(self):
        for x in xrange(0, 3):
            addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
            premium = AddonPremium.objects.create(addon=addon)
            premium.update(created=datetime.today() -
                                   timedelta(days=x, seconds=5))

    def test_delete(self):
        eq_(AddonPremium.objects.count(), 3)
        clean_out_addonpremium(days=2)
        eq_(AddonPremium.objects.count(), 2)
        clean_out_addonpremium(days=1)
        eq_(AddonPremium.objects.count(), 1)

    def test_doesnt_delete(self):
        Addon.objects.all().update(premium_type=amo.ADDON_PREMIUM)
        clean_out_addonpremium(days=1)
        eq_(AddonPremium.objects.count(), 3)


class TestPendingRefunds(amo.tests.TestCase):
    fixtures = ['base/337141-steamcube', 'base/users']

    def create_refund(self, webapp=None):
        webapp = webapp if webapp else self.webapp
        contribution = Contribution.objects.create(addon=webapp)
        return Refund.objects.create(contribution=contribution)

    def setUp(self):
        self.webapp = Addon.objects.get(pk=337141)
        self.author = self.webapp.authors.all()[0]
        self.refund = self.create_refund()

    def test_none(self):
        self.refund.delete()
        mail_pending_refunds()
        eq_(len(mail.outbox), 0)

    def test_not_pending(self):
        for status in [amo.REFUND_APPROVED, amo.REFUND_APPROVED_INSTANT,
                       amo.REFUND_DECLINED]:
            self.refund.update(status=status)
            mail_pending_refunds()
        eq_(len(mail.outbox), 0)

    def test_single(self):
        mail_pending_refunds()
        eq_(len(mail.outbox), 1)
        assert str(self.webapp.name) in mail.outbox[0].body
        assert '1 request' in mail.outbox[0].body
        assert mail.outbox[0].to == [self.author.email]

    def test_plural(self):
        self.create_refund()
        mail_pending_refunds()
        eq_(len(mail.outbox), 1)
        assert '2 requests' in mail.outbox[0].body

    def test_two_owners(self):
        user = UserProfile.objects.exclude(pk=self.author.pk)[0]
        AddonUser.objects.create(user=user, addon=self.webapp)
        mail_pending_refunds()
        eq_(len(mail.outbox), 2)
        emails = set([m.to[0] for m in mail.outbox])
        eq_(set([self.author.email, user.email]), emails)

    def test_one_owner_one_other(self):
        user = UserProfile.objects.exclude(pk=self.author.pk)[0]
        AddonUser.objects.create(user=user, addon=self.webapp,
                                 role=amo.AUTHOR_ROLE_VIEWER)
        mail_pending_refunds()
        eq_(len(mail.outbox), 1)
        assert mail.outbox[0].to == [self.author.email]

    def test_two_addons(self):
        other = Addon.objects.create(app_slug='something-else',
                                     name='cthulhu', type=amo.ADDON_WEBAPP)
        AddonUser.objects.create(user=self.author, addon=other,
                                 role=amo.AUTHOR_ROLE_OWNER)
        self.create_refund(other)
        mail_pending_refunds()
        eq_(len(mail.outbox), 1)
        eq_(mail.outbox[0].body.count('1 request'), 2)
