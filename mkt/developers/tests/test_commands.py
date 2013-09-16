# -*- coding: utf-8 -*-
from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon, AddonPremium
from mkt.developers.management.commands import cleanup_addon_premium
from mkt.site.fixtures import fixture


class TestCommandViews(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = self.get_webapp()

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_cleanup_addonpremium(self):
        self.make_premium(self.webapp)
        eq_(AddonPremium.objects.all().count(), 1)
        cleanup_addon_premium.Command().handle()
        eq_(AddonPremium.objects.all().count(), 1)
        self.webapp.update(premium_type=amo.ADDON_FREE)
        cleanup_addon_premium.Command().handle()
        eq_(AddonPremium.objects.all().count(), 0)
