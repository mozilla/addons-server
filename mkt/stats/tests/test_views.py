import datetime
import json

from nose.tools import eq_
import waffle

from access.models import Group, GroupUser
import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from mkt.webapps.models import Installed
from mkt.stats import views, search
from mkt.stats.views import pad_missing_stats
from users.models import UserProfile


class StatsTest(amo.tests.ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.CONTRIBUTION_SERIES = ('revenue', 'sales', 'refunds')

        # set up apps
        waffle.models.Switch.objects.create(name='app-stats', active=True)
        self.public_app = amo.tests.app_factory(name='public',
            app_slug='pub', type=1, status=4, public_stats=True)
        self.private_app = amo.tests.app_factory(name='private',
            app_slug='priv', type=1, status=4, public_stats=False)
        self.url_args = {'start': '20090601', 'end': '20090930',
            'app_slug': self.private_app.app_slug}

        # normal user
        self.user_profile = UserProfile.objects.get(username='regularuser')

    def login_as_visitor(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def get_view_response(self, view, **kwargs):
        view_args = self.url_args.copy()
        head = kwargs.pop('head', False)
        view_args.update(kwargs)
        url = reverse(view, kwargs=view_args)
        if head:
            return self.client.head(url, follow=True)
        return self.client.get(url, follow=True)

    def views_gen(self, **kwargs):
        # common set of views
        for series in views.SERIES:
            for group in views.SERIES_GROUPS:
                view = 'mkt.stats.%s_series' % series
                args = kwargs.copy()
                args['group'] = group
                yield (view, args)

    def public_views_gen(self, **kwargs):
        # all views are potentially public, except for contributions
        for view, args in self.views_gen(**kwargs):
            if not view in ['mkt.stats.%s_series' % series for series in
                            self.CONTRIBUTION_SERIES]:
                yield (view, args)

    def private_views_gen(self, **kwargs):
        # only contributions views are always private
        for view, args in self.views_gen(**kwargs):
            if view in ['mkt.stats.%s_series' % series for series in
                        self.CONTRIBUTION_SERIES]:
                yield (view, args)


class TestStatsPermissions(StatsTest):
    """Tests to make sure all restricted data remains restricted."""
    mock_es = True  # We're checking only headers, not content.

    def _check_it(self, views, status):
        for view, kwargs in views:
            response = self.get_view_response(view, head=True, **kwargs)
            eq_(response.status_code, status,
                'unexpected http status for %s. got %s. expected %s' % (
                    view, response.status_code, status))

    def test_private_app_no_groups(self):
        # Logged in but no groups
        self.login_as_visitor()
        self._check_it(self.private_views_gen(format='json'), 403)

    def test_private_app_stats_group(self):
        # Logged in with stats group.
        group = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=self.user_profile, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(format='json'), 200)
        self._check_it(self.private_views_gen(format='json'), 403)

    def test_private_app_contrib_stats_group(self):
        # Logged in with stats and contrib stats group.
        group1 = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=self.user_profile, group=group1)
        group2 = Group.objects.create(name='Revenue Stats',
                                      rules='RevenueStats:View')
        GroupUser.objects.create(user=self.user_profile, group=group2)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(format='json'), 200)
        self._check_it(self.private_views_gen(format='json'), 200)

    def test_private_app_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.private_views_gen(format='json'), 403)

    def test_public_app_no_groups(self):
        # Logged in but no groups
        self.login_as_visitor()
        self._check_it(self.public_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 200)
        self._check_it(self.private_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 403)

    def test_public_app_stats_group(self):
        # Logged in with stats group.
        group = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=self.user_profile, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 200)
        self._check_it(self.private_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 403)

    def test_public_app_contrib_stats_group(self):
        # Logged in with stats and contrib stats group.
        group1 = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=self.user_profile, group=group1)
        group2 = Group.objects.create(name='Revenue Stats',
                                      rules='RevenueStats:View')
        GroupUser.objects.create(user=self.user_profile, group=group2)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 200)
        self._check_it(self.private_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 200)

    def test_public_app_anonymous(self):
        # Not logged in
        self.client.logout()
        self._check_it(self.public_views_gen(app_slug=self.public_app.app_slug,
            format='json'), 200)
        self._check_it(self.private_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 403)


class TestInstalled(amo.tests.ESTestCase):
    es = True
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.today = datetime.date.today()
        self.webapp = Addon.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        self.client.login(username='admin@mozilla.com', password='password')
        self.in_ = Installed.objects.create(addon=self.webapp, user=self.user)
        Installed.index(search.extract_installed_count(self.in_),
                        id=self.in_.pk)
        self.refresh('users_install')

    def get_url(self, start, end, fmt='json'):
        return reverse('mkt.stats.installs_series',
                       args=[self.webapp.app_slug, 'day',
                             start.strftime('%Y%m%d'),
                             end.strftime('%Y%m%d'), fmt])

    def test_installed(self):
        res = self.client.get(self.get_url(self.today, self.today))
        data = json.loads(res.content)
        eq_(data[0]['count'], 1)

    def test_installed_anon(self):
        self.client.logout()
        res = self.client.get(self.get_url(self.today, self.today))
        eq_(res.status_code, 403)

    def test_installed_anon_public(self):
        self.client.logout()
        self.webapp.update(public_stats=True)
        res = self.client.get(self.get_url(self.today, self.today))
        eq_(res.status_code, 200)


class TestPadMissingStats(amo.tests.ESTestCase):

    def test_basic(self):
        days = [datetime.date(2012, 4, 29), datetime.date(2012, 5, 1),
                datetime.date(2012, 5, 3), datetime.date(2012, 5, 5)]
        expected_days = [datetime.date(2012, 4, 30), datetime.date(2012, 5, 2),
                         datetime.date(2012, 5, 4)]

        dummies = pad_missing_stats(days, 'day')
        for day in expected_days:
            assert day in [dummy['date'] for dummy in dummies]

    def test_with_date_range(self):
        date_range = (datetime.date(2012, 5, 1), datetime.date(2012, 5, 5))

        days = [datetime.date(2012, 5, 3)]
        expected_days = [datetime.date(2012, 5, 2), datetime.date(2012, 5, 4)]

        dummies = pad_missing_stats(days, 'day', date_range=date_range)
        for day in expected_days:
            assert day in [dummy['date'] for dummy in dummies]

    def test_with_fields(self):
        fields = ['test_field', 'fest_tield']

        days = [datetime.date(2012, 5, 1), datetime.date(2012, 5, 3)]
        dummies = pad_missing_stats(days, 'day', fields=fields)
        for dummy in dummies:
            for field in fields:
                assert field in dummy

    def test_group_week(self):
        days = [datetime.date(2012, 5, 1), datetime.date(2012, 5, 15)]
        expected_days = [datetime.date(2012, 5, 8)]

        dummies = pad_missing_stats(days, 'week')
        for day in expected_days:
            assert day in [dummy['date'] for dummy in dummies]

    def test_group_month(self):
        days = [datetime.date(2012, 5, 1), datetime.date(2012, 7, 1)]
        expected_days = [datetime.date(2012, 6, 1)]

        dummies = pad_missing_stats(days, 'month')
        for day in expected_days:
            assert day in [dummy['date'] for dummy in dummies]
