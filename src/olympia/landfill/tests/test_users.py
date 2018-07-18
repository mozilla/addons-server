# -*- coding: utf-8 -*-
from olympia import amo
from olympia.addons.models import Addon, AddonCategory, AddonUser, Category
from olympia.amo.tests import TestCase
from olympia.landfill.user import (
    generate_addon_user_and_category,
    generate_user,
)
from olympia.users.models import UserProfile


class RatingsTests(TestCase):
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
