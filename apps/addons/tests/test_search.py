from nose.tools import eq_

import amo.tests
from addons.models import (Addon, attach_categories, attach_devices,
                           attach_tags, attach_translations)
from addons.search import extract


class TestExtract(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.attrs = ('id', 'slug', 'app_slug', 'created', 'last_updated',
                      'weekly_downloads', 'average_daily_users', 'status',
                      'type', 'hotness', 'is_disabled', 'premium_type',
                      'uses_flash')
        self.transforms = (attach_categories, attach_devices,
                           attach_tags, attach_translations)

    def _extract(self):
        qs = Addon.objects.filter(id__in=[3615])
        for t in self.transforms:
            qs = qs.transform(t)
        self.addon = list(qs)[0]
        return extract(self.addon)

    def test_extract_attributes(self):
        extracted = self._extract()
        for attr in self.attrs:
            eq_(extracted[attr], getattr(self.addon, attr))
