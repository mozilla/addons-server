# -*- coding: utf-8 -*-
from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import TestCase
from olympia.landfill.ratings import generate_ratings
from olympia.ratings.models import Rating
from olympia.users.models import UserProfile


class RatingsTests(TestCase):

    def setUp(self):
        super(RatingsTests, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_ratings_generation(self):
        generate_ratings(self.addon, 3)
        assert Rating.objects.all().count() == 3
        assert UserProfile.objects.count() == 3
        for n, review in enumerate(Rating.objects.all().order_by('pk')):
            assert review.addon == self.addon
            assert unicode(review.body) == u'Test Review %d' % (n + 1)
            assert review.user.email.endswith('@example.com')
