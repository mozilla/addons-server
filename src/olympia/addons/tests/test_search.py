from nose.tools import eq_

from olympia.amo.tests import TestCase
from olympia.addons.models import (
    Addon, attach_categories, attach_tags, attach_translations)
from olympia.addons.search import extract


class TestExtract(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestExtract, self).setUp()
        self.attrs = ('id', 'slug', 'created', 'last_updated',
                      'weekly_downloads', 'average_daily_users', 'status',
                      'type', 'hotness', 'is_disabled')
        self.transforms = (attach_categories, attach_tags, attach_translations)

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
