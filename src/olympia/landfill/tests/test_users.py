# -*- coding: utf-8 -*-
from nose.tools import eq_

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon, AddonCategory, AddonUser, Category
from olympia.users.models import UserProfile
from olympia.landfill.user import (
    generate_addon_user_and_category, generate_user)


class RatingsTests(TestCase):

    def setUp(self):
        super(RatingsTests, self).setUp()
        self.email = 'nobody@mozilla.org'
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_generate_addon_user_and_category(self):
        user = UserProfile.objects.create(email=self.email)
        category = Category.objects.create(type=amo.ADDON_PERSONA)
        generate_addon_user_and_category(self.addon, user, category)
        eq_(AddonCategory.objects.all().count(), 1)
        eq_(AddonUser.objects.all().count(), 1)

    def test_generate_user(self):
        generate_user(self.email)
        eq_(UserProfile.objects.last().email, self.email)
