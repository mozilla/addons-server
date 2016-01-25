# -*- coding: utf-8 -*-

import amo
import amo.tests
from addons.models import Addon, AddonCategory, AddonUser, Category
from users.models import UserProfile
from landfill.user import generate_addon_user_and_category, generate_user


class RatingsTests(amo.tests.TestCase):

    def setUp(self):
        super(RatingsTests, self).setUp()
        self.email = 'nobody@mozilla.org'
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_generate_addon_user_and_category(self):
        user = UserProfile.objects.create(email=self.email)
        category = Category.objects.create(type=amo.ADDON_PERSONA)
        generate_addon_user_and_category(self.addon, user, category)
        assert AddonCategory.objects.all().count() == 1
        assert AddonUser.objects.all().count() == 1

    def test_generate_user(self):
        generate_user(self.email)
        assert UserProfile.objects.last().email == self.email
