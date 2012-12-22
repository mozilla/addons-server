# -*- coding: utf-8 -*-
import datetime

from django.conf import settings
from django.core import mail
from django.utils.encoding import smart_str

import mock
from nose.tools import eq_

from addons.models import AddonUser
import amo.tests
from mkt.ratings.cron import email_daily_ratings
from reviews.models import Review
from users.models import UserProfile


@mock.patch.object(settings, 'SEND_REAL_EMAIL', True)
class TestEmailDailyRatings(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.app = amo.tests.app_factory(name='test')
        self.app2 = amo.tests.app_factory(name='test2')

        self.user = UserProfile.objects.get(username='regularuser')
        AddonUser.objects.create(addon=self.app, user=self.user)
        AddonUser.objects.create(addon=self.app2, user=self.user)
        yesterday = datetime.datetime.today() - datetime.timedelta(1)

        # Create one review for app, two reviews for app2.
        self.app1_review = Review.objects.create(
            addon=self.app, user=self.user, rating=1,
            body='sux, I want my money back.')
        self.app1_review.update(created=yesterday)

        self.app2_review = Review.objects.create(
            addon=self.app2, user=self.user, rating=4,
            body='waste of two seconds of my life.')
        self.app2_review.update(created=yesterday)

        self.app2_review2 = Review.objects.create(
            addon=self.app2, user=self.user, rating=5,
            body='a++ would play again')
        self.app2_review2.update(created=yesterday)

    def test_emails_goes_out(self):
        # Test first email have one rating, second email has two ratings.
        email_daily_ratings()
        eq_(len(mail.outbox), 2)
        eq_(mail.outbox[0].to, [self.user.email])
        eq_(mail.outbox[1].to, [self.user.email])
        eq_(str(self.app1_review.body) in smart_str(mail.outbox[0].body), True)
        eq_(str(self.app2_review.body) in smart_str(mail.outbox[1].body), True)
        eq_(str(self.app2_review2.body) in smart_str(mail.outbox[1].body),
            True)
        eq_(str(self.app2_review.body) not in smart_str(mail.outbox[0].body),
            True)
        eq_(str(self.app2_review.body) not in smart_str(mail.outbox[0].body),
            True)
