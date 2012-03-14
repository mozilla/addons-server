from nose.tools import eq_
import waffle

import amo
import amo.tests
from market.models import AddonPremium, Price
from users.models import UserProfile
from versions.models import Version
from mkt.webapps.models import Webapp


class WebappTest(amo.tests.TestCase):

    def setUp(self):
        self.webapp = Webapp.objects.create(name='woo', app_slug='yeah',
            weekly_downloads=9999, status=amo.STATUS_PUBLIC)
        self.webapp._current_version = (Version.objects
                                        .create(addon=self.webapp))
        self.webapp.save()

        self.webapp_url = self.url = self.webapp.get_url_path()


class PaidAppMixin(object):

    def setup_paid(self, type_=None):
        type_ = amo.ADDON_PREMIUM if type_ is None else type_
        self.free = [
            Webapp.objects.get(id=337141),
            amo.tests.addon_factory(type=amo.ADDON_WEBAPP),
        ]

        self.paid = []
        for x in xrange(1, 3):
            price = Price.objects.create(price=x)
            addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
                                            weekly_downloads=x * 100)
            AddonPremium.objects.create(price=price, addon=addon)
            addon.update(premium_type=type_)
            self.paid.append(addon)

        # For measure add some disabled free apps ...
        amo.tests.addon_factory(type=amo.ADDON_WEBAPP, disabled_by_user=True)
        amo.tests.addon_factory(type=amo.ADDON_WEBAPP, status=amo.STATUS_NULL)

        # ... and some disabled paid apps.
        addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
            disabled_by_user=True, premium_type=amo.ADDON_PREMIUM)
        AddonPremium.objects.create(price=price, addon=addon)
        addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
            status=amo.STATUS_NULL, premium_type=amo.ADDON_PREMIUM)
        AddonPremium.objects.create(price=price, addon=addon)

        self.both = sorted(self.free + self.paid,
                           key=lambda x: x.weekly_downloads, reverse=True)
        self.free = sorted(self.free, key=lambda x: x.weekly_downloads,
                           reverse=True)
        self.paid = sorted(self.paid, key=lambda x: x.weekly_downloads,
                           reverse=True)


class TestPremium(PaidAppMixin, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.setup_paid()
        eq_(self.free, list(Webapp.objects.top_free()))
        eq_(self.paid, list(Webapp.objects.top_paid()))
