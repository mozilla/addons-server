from nose.tools import eq_

import amo.tests
from addons.models import Addon


class TestES(amo.tests.ESTestCase):
    es = True

    # This should go in a test for the cron.
    def test_indexed_count(self):
        # Did all the right addons get indexed?
        eq_(Addon.search().filter(type=1, is_disabled=False).count(),
            Addon.objects.filter(disabled_by_user=False,
                                 status__in=amo.VALID_STATUSES).count())

    def test_clone(self):
        # Doing a filter creates a new ES object.
        qs = Addon.search()
        qs2 = qs.filter(type=1)
        eq_(qs._build_query(), {'fields': ['id']})
        eq_(qs2._build_query(), {'fields': ['id'],
                                 'filter': {'term': {'type': 1}}})

    def test_filter(self):
        qs = Addon.search().filter(type=1)
        eq_(qs._build_query(), {'fields': ['id'],
                                'filter': {'term': {'type': 1}}})

    def test_in_filter(self):
        qs = Addon.search().filter(type__in=[1, 2])
        eq_(qs._build_query(), {'fields': ['id'],
                                'filter': {'in': {'type': [1, 2]}}})

    def test_and(self):
        qs = Addon.search().filter(type=1, category__in=[1, 2])
        eq_(qs._build_query(), {'fields': ['id'],
                                'filter': {'and': [
                                    {'term': {'type': 1}},
                                    {'in': {'category': [1, 2]}},
                                ]}})

    def test_query(self):
        qs = Addon.search().query(type=1)
        eq_(qs._build_query(), {'fields': ['id'],
                                'query': {'term': {'type': 1}}})

    def test_values(self):
        qs = Addon.search().values('app')
        eq_(qs._build_query(), {'fields': ['id', 'app']})

    def test_order_by(self):
        qs = Addon.search().order_by('-rating')
        eq_(qs._build_query(), {'fields': ['id'],
                                'sort': [{'rating': 'desc'}]})

        qs = Addon.search().order_by('rating')
        eq_(qs._build_query(), {'fields': ['id'],
                                'sort': ['rating']})

    def test_slice(self):
        qs = Addon.search()[5:12]
        eq_(qs._build_query(), {'fields': ['id'],
                                'from': 5,
                                'size': 7})

    def test_getitem(self):
        addons = list(Addon.search())
        eq_(addons[0], Addon.search()[0])

    def test_iter(self):
        qs = Addon.search().filter(type=1, is_disabled=False)
        eq_(len(qs), 4)
        eq_(len(list(qs)), 4)

    def test_count(self):
        eq_(Addon.search().count(), 6)
