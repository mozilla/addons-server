import json

from nose import SkipTest
from nose.tools import eq_

import amo
from addons.models import Category
from amo.urlresolvers import reverse
from search.tests.test_views import TestAjaxSearch

import mkt
from mkt.webapps.models import AddonExcludedRegion as AER, Webapp


class TestSuggestions(TestAjaxSearch):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        super(TestSuggestions, self).setUp()
        self.url = reverse('search.apps_ajax')

        self.c1 = Category.objects.create(name='groovy',
            type=amo.ADDON_WEBAPP)
        self.c2 = Category.objects.create(name='awesome',
            type=amo.ADDON_WEBAPP)

        self.w1 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
            name='groovy app 1')
        self.w2 = Webapp.objects.create(status=amo.STATUS_PUBLIC,
            name='awesome app 2')
        self.w3 = Webapp.objects.get(pk=337141)

        self.w1.addoncategory_set.create(category=self.c1)
        self.w2.addoncategory_set.create(category=self.c2)

        self.reindex(Webapp)

    def check_suggestions(self, url, params, addons=()):
        r = self.client.get(url + '?' + params)
        eq_(r.status_code, 200)

        data = json.loads(r.content)
        print data
        print addons
        eq_(len(data), len(addons))

        data = sorted(data, key=lambda x: x['name'])
        addons = sorted(addons, key=lambda x: x.name)
        eq_(len(data), len(addons))

        for got, expected in zip(data, addons):
            eq_(got['name'], unicode(expected.name))
            eq_(int(got['id']), expected.id)

    def test_webapp_search(self):
        self.check_suggestions(self.url, 'q=app&category=',
            addons=[self.w1, self.w2, self.w3])
        self.check_suggestions(
            self.url, 'q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(
            self.url, 'q=app&category=%d' % self.c2.id, addons=[self.w2])

    def test_region_exclusions(self):
        raise SkipTest  # disable until #789977 gets clarified
        AER.objects.create(addon=self.w2, region=mkt.regions.BR.id)

        self.check_suggestions(self.url,
            'region=br&q=app&category=', addons=[self.w1])
        self.check_suggestions(self.url,
            'region=br&q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(self.url,
            'region=br&q=app&category=%d' % self.c2.id, addons=[])

        self.check_suggestions(self.url,
            'region=ca&q=app&category=', addons=[self.w1, self.w2])
        self.check_suggestions(self.url,
            'region=ca&q=app&category=%d' % self.c1.id, addons=[self.w1])
        self.check_suggestions(self.url,
            'region=ca&q=app&category=%d' % self.c2.id, addons=[self.w2])
