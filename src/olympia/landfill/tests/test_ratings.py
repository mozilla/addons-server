# -*- coding: utf-8 -*-
from nose.tools import eq_

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon, Review
from olympia.landfill.ratings import generate_ratings


class RatingsTests(TestCase):

    def setUp(self):
        super(RatingsTests, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_ratings_generation(self):
        generate_ratings(self.addon, 1)
        eq_(Review.objects.all().count(), 1)
        eq_(Review.objects.last().addon, self.addon)
        eq_(unicode(Review.objects.last().title), u'Test Review 1')
        eq_(Review.objects.last().user.email, u'testuser1@example.com')
