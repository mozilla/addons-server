import json

import test_utils
from nose.tools import ok_

from django.contrib.auth.models import AnonymousUser

import amo
from addons.models import Category

from mkt import regions
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.regions import set_region
from mkt.reviewers.forms import ApiReviewersSearchForm
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

        self.category = Category.objects.create(name='games', slug='games',
                                                type=amo.ADDON_WEBAPP)
        # Pick a region that has relatively few filters.
        set_region(regions.UK.slug)

        self.form_class = ApiSearchForm

    def _grant(self, rules):
        self.grant_permission(self.profile, rules)
        self.req.groups = self.profile.groups.all()

    def _filter(self, req, filters, sorting=None, **kwargs):
        form = self.form_class(filters)
        if form.is_valid():
            qs = Webapp.from_search(self.req, **kwargs)
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
        self.form_class = ApiReviewersSearchForm
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
        qs = self._filter(self.req, {'cat': self.category.slug})
        ok_({'term': {'category': self.category.slug}} in qs['filter']['and'])

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
        qs = self._filter(self.req, {'app_type': ['hosted']})
        ok_({'in': {'app_type': [1]}} in qs['filter']['and'])

    def test_manifest_url(self):
        url = 'http://hy.fr/manifest.webapp'
        qs = self._filter(self.req, {'manifest_url': url})
        ok_({'term': {'manifest_url': url}} in qs['filter']['and'])

    def test_offline(self):
        """Ensure we are filtering by offline-capable apps."""
        qs = self._filter(self.req, {'offline': 'True'})
        ok_({'term': {'is_offline': True}} in qs['filter']['and'])

    def test_online(self):
        """Ensure we are filtering by apps that require online access."""
        qs = self._filter(self.req, {'offline': 'False'})
        ok_({'term': {'is_offline': False}} in qs['filter']['and'])

    def test_offline_and_online(self):
        """Ensure we are not filtering by offline/online by default."""
        qs = self._filter(self.req, {})
        ok_({'term': {'is_offline': True}} not in qs['filter']['and'])
        ok_({'term': {'is_offline': False}} not in qs['filter']['and'])

    def test_languages(self):
        qs = self._filter(self.req, {'languages': 'fr'})
        ok_({'in': {'supported_locales': ['fr']}} in qs['filter']['and'])

        qs = self._filter(self.req, {'languages': 'ar,en-US'})
        ok_({'in': {'supported_locales': ['ar', 'en-US']}}
            in qs['filter']['and'])

    def test_region_exclusions(self):
        qs = self._filter(self.req, {'q': 'search terms'}, region=regions.CO)
        ok_({'not': {'filter': {'term': {'region_exclusions': regions.CO.id}}}}
            in qs['filter']['and'])

    def test_region_exclusions_override(self):
        self.create_flag('override-region-exclusion')
        qs = self._filter(self.req, {'q': 'search terms'}, region=regions.CO)
        ok_({'not': {'filter': {'term': {'region_exclusions': regions.CO.id}}}}
            not in qs['filter']['and'])
