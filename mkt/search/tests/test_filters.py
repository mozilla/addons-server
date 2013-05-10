import json

import test_utils
from nose.tools import ok_

from django.contrib.auth.models import AnonymousUser

import amo
from addons.models import Category
from mkt import regions
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.regions import set_region
from mkt.search.forms import ApiSearchForm, DEVICE_CHOICES_IDS
from mkt.search.views import _filter_search
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


class TestSearchFilters(BaseOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestSearchFilters, self).setUp()
        self.req = test_utils.RequestFactory().get('/')
        self.req.user = AnonymousUser()

        self.category = Category.objects.create(name='games',
                                                type=amo.ADDON_WEBAPP)
        # Pick a region that has relatively few filters.
        set_region(regions.UK.slug)

    def _grant(self, rules):
        self.grant_permission(self.profile, rules)
        self.req.groups = self.profile.groups.all()

    def _filter(self, req, filters, sorting=None):
        form = ApiSearchForm(filters)
        if form.is_valid():
            qs = Webapp.from_search().facet('category')
            return _filter_search(
                self.req, qs, form.cleaned_data, sorting)._build_query()
        else:
            return form.errors.copy()

    def test_q(self):
        qs = self._filter(self.req, {'q': 'search terms'})
        qs_str = json.dumps(qs)
        ok_('"query": "search terms"' in qs_str)
        # TODO: Could do more checking here.

    def _addon_type_check(self, query, expected=amo.ADDON_WEBAPP):
        qs = self._filter(self.req, query)
        ok_({'term': {'type': expected}} in qs['filter']['and'],
            'Unexpected type. Expected: %s.' % expected)

    def test_addon_type(self):
        # Test all that should end up being ADDON_WEBAPP.
        # Note: Addon type permission can't be checked here b/c the acl check
        # happens in the view, not the _filter_search call.
        self._addon_type_check({})
        self._addon_type_check({'type': 'app'})
        self._addon_type_check({'type': 'theme'})
        # Test a bad value.
        qs = self._filter(self.req, {'type': 'vindaloo'})
        ok_(u'Select a valid choice' in qs['type'][0])

    def _status_check(self, query, expected=amo.STATUS_PUBLIC):
        qs = self._filter(self.req, query)
        ok_({'term': {'status': expected}} in qs['filter']['and'],
            'Unexpected status. Expected: %s.' % expected)

    def test_status(self):
        # Test all that should end up being public.
        # Note: Status permission can't be checked here b/c the acl check
        # happens in the view, not the _filter_search call.
        self._status_check({})
        self._status_check({'status': 'public'})
        self._status_check({'status': 'rejected'})
        # Test a bad value.
        qs = self._filter(self.req, {'status': 'vindaloo'})
        ok_(u'Select a valid choice' in qs['status'][0])

    def test_category(self):
        qs = self._filter(self.req, {'cat': self.category.pk})
        ok_({'term': {'category': self.category.pk}} in qs['filter']['and'])

    def test_device(self):
        qs = self._filter(self.req, {'device': 'desktop'})
        ok_({'term': {
            'device': DEVICE_CHOICES_IDS['desktop']}} in qs['filter']['and'])

    def test_premium_types(self):
        ptype = lambda p: amo.ADDON_PREMIUM_API_LOOKUP.get(p)
        # Test a single premium type.
        qs = self._filter(self.req, {'premium_types': ['free']})
        ok_({'in': {'premium_type': [ptype('free')]}} in qs['filter']['and'])
        # Test many premium types.
        qs = self._filter(self.req, {'premium_types': ['free', 'free-inapp']})
        ok_({'in': {'premium_type': [ptype('free'), ptype('free-inapp')]}}
            in qs['filter']['and'])
        # Test a non-existent premium type.
        qs = self._filter(self.req, {'premium_types': ['free', 'platinum']})
        ok_(u'Select a valid choice' in qs['premium_types'][0])

    def test_app_type(self):
        qs = self._filter(self.req, {'app_type': 'hosted'})
        ok_({'term': {'app_type': 1}} in qs['filter']['and'])

    def test_region(self):
        # Test regions that affect search filters.

        # Test region with no filters.
        qs = self._filter(self.req, {'q': 'yolo'})
        qs_str = json.dumps(qs)
        ok_('not' not in qs_str)

        # Test child-excluded region.
        set_region(list(regions.CHILD_EXCLUDED)[0].slug)
        qs = self._filter(self.req, {'q': 'yolo'})
        ok_({'not': {'filter': {'term': {'flag_child': True}}}}
            in qs['filter']['and'])

        # Test adult-excluded region.
        set_region(list(regions.ADULT_EXCLUDED)[0].slug)
        qs = self._filter(self.req, {'q': 'yolo'})
        ok_({'not': {'filter': {'term': {'flag_adult': True}}}}
            in qs['filter']['and'])
