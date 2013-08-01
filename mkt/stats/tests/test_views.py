import csv
import datetime
from decimal import Decimal
import json
import random

from nose.tools import eq_
from test_utils import RequestFactory

from access.models import Group, GroupUser
import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUser
from apps.stats.models import GlobalStat
from market.models import Price
from mkt.inapp_pay.models import InappConfig, InappPayment
from mkt.webapps.models import Installed
from mkt.site.fixtures import fixture
from mkt.stats import search, tasks, views
from mkt.stats.views import (FINANCE_SERIES, get_series_column,
                             get_series_line, pad_missing_stats)
from stats.models import Contribution
from users.models import UserProfile


class StatsTest(amo.tests.ESTestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        super(StatsTest, self).setUp()
        self.user = UserProfile.objects.get(username='regularuser')

        self.public_app = amo.tests.app_factory(name='public',
            app_slug='pub', type=1, status=4, public_stats=True)
        self.private_app = amo.tests.app_factory(name='private',
            app_slug='priv', type=1, status=4, public_stats=False)
        self.url_args = {'start': '20090601', 'end': '20090930',
            'app_slug': self.private_app.app_slug}

        # set up inapps
        self.inapp_name = 'test_inapp'
        self.public_config = InappConfig.objects.create(
            addon=self.public_app, public_key='asd')
        self.private_config = InappConfig.objects.create(
            addon=self.private_app, public_key='fgh')
        c = Contribution.objects.create(addon_id=self.public_app.pk,
                                        user=self.user, amount=5)
        InappPayment.objects.create(config=self.public_config, contribution=c,
                                    name=self.inapp_name)
        c = Contribution.objects.create(addon_id=self.private_app.pk,
                                        user=self.user, amount=5)
        InappPayment.objects.create(config=self.private_config, contribution=c,
                                    name=self.inapp_name)

    def login_as_visitor(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def get_view_response(self, view, **kwargs):
        view_args = self.url_args.copy()
        head = kwargs.pop('head', False)
        view_args.update(kwargs)
        if '_inapp' in view:
            view_args['inapp'] = self.inapp_name
        url = reverse(view, kwargs=view_args)
        if head:
            return self.client.head(url, follow=True)
        return self.client.get(url, follow=True)

    def views_gen(self, **kwargs):
        # common set of views
        for series in views.SERIES:
            if series == 'my_apps':
                # skip my_apps, as it has different routes
                continue
            for group in views.SERIES_GROUPS:
                view = 'mkt.stats.%s_series' % series
                args = kwargs.copy()
                args['group'] = group
                yield (view, args)

    def public_views_gen(self, **kwargs):
        # all views are potentially public, except for contributions
        for view, args in self.views_gen(**kwargs):
            if not view in ['mkt.stats.%s_series' % series for series in
                            FINANCE_SERIES]:
                yield (view, args)

    def private_views_gen(self, **kwargs):
        # only contributions views are always private
        for view, args in self.views_gen(**kwargs):
            if view in ['mkt.stats.%s_series' % series for series in
                        FINANCE_SERIES]:
                yield (view, args)


class TestStatsPermissions(StatsTest):
    """Tests to make sure all restricted data remains restricted."""

    @amo.tests.mock_es  # We're checking only headers, not content.
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
        GroupUser.objects.create(user=self.user, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(format='json'), 200)
        self._check_it(self.private_views_gen(format='json'), 403)

    def test_private_app_contrib_stats_group(self):
        # Logged in with stats and contrib stats group.
        group1 = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=self.user, group=group1)
        group2 = Group.objects.create(name='Revenue Stats',
                                      rules='RevenueStats:View')
        GroupUser.objects.create(user=self.user, group=group2)
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
        GroupUser.objects.create(user=self.user, group=group)
        self.login_as_visitor()

        self._check_it(self.public_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 200)
        self._check_it(self.private_views_gen(
            app_slug=self.public_app.app_slug, format='json'), 403)

    def test_public_app_contrib_stats_group(self):
        # Logged in with stats and contrib stats group.
        group1 = Group.objects.create(name='Stats', rules='Stats:View')
        GroupUser.objects.create(user=self.user, group=group1)
        group2 = Group.objects.create(name='Revenue Stats',
                                      rules='RevenueStats:View')
        GroupUser.objects.create(user=self.user, group=group2)
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

    def test_non_public_app_redirect(self):
        # Non-public status redirects to detail page.
        app = amo.tests.app_factory(status=2, public_stats=True)
        response = self.client.get(app.get_stats_url())
        eq_(response.status_code, 302)

    def test_non_public_app_owner_no_redirect(self):
        # Non-public status, but owner of app, does not redirect to detail
        # page.
        self.login_as_visitor()
        app = amo.tests.app_factory(status=2, public_stats=True)
        AddonUser.objects.create(addon_id=app.id, user=self.user)
        response = self.client.get(app.get_stats_url())
        eq_(response.status_code, 200)


class TestMyApps(StatsTest):

    def setUp(self):
        super(TestMyApps, self).setUp()
        self.req = RequestFactory().get('/')
        self.req.amo_user = self.user
        AddonUser.objects.create(addon=self.public_app, user=self.user)
        Installed.objects.create(addon=self.public_app, user=self.user)

    def test_anonymous(self):
        del self.req.amo_user
        eq_(views._my_apps(self.req), [])

    def test_some(self):
        eq_(views._my_apps(self.req), [self.public_app])

    def test_deleted(self):
        self.public_app.update(status=amo.STATUS_DELETED)
        eq_(views._my_apps(self.req), [])


class TestInstalled(amo.tests.ESTestCase):
    test_es = True
    fixtures = fixture('user_admin', 'group_admin', 'user_admin_group',
                       'user_999', 'webapp_337141')

    def setUp(self):
        self.today = datetime.date.today()
        self.webapp = Addon.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        self.client.login(username='admin@mozilla.com', password='password')
        self.in_ = Installed.objects.create(addon=self.webapp, user=self.user)
        installed = {'addon': self.in_.addon.id, 'created': self.in_.created}
        Installed.index(search.get_installed_daily(installed),
                        id=self.in_.pk)
        self.refresh('users_install')

    def get_url(self, start, end, fmt='json'):
        return reverse('mkt.stats.installs_series',
                       args=[self.webapp.app_slug, 'day',
                             start.strftime('%Y%m%d'),
                             end.strftime('%Y%m%d'), fmt])

    def get_multiple_url(self, start, end, fmt='json'):
        return reverse('mkt.stats.my_apps_series',
                       args=['day',
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

    def setup_multiple(self):
        self.client.login(username=self.user.email, password='password')
        AddonUser.objects.create(addon=self.webapp, user=self.user)

    def test_multiple_json(self):
        self.setup_multiple()
        res = self.client.get(self.get_multiple_url(self.today, self.today))
        eq_(json.loads(res.content)[0]['name'], self.webapp.name)

    def test_multiple_csv(self):
        self.setup_multiple()
        res = self.client.get(self.get_multiple_url(self.today, self.today,
                                                    fmt='csv'))
        rows = list(csv.reader(res.content.split('\n')))
        eq_(rows[5][0], str(self.webapp.name))

    def test_anonymous(self):
        self.client.logout()
        res = self.client.get(reverse('mkt.stats.my_apps_overview'))
        self.assertLoginRequired(res)


class TestGetSeriesLine(amo.tests.ESTestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        # Create apps and contributions to index.
        self.app = amo.tests.app_factory()
        user = UserProfile.objects.get(username='regularuser')
        price_tier = Price.objects.create(price='0.99')

        # Create a sale for each day in the expected range.
        self.expected_days = (1, 2, 3, 4, 5)
        for day in self.expected_days:
            # Create different amounts of contribs for each day.
            for x in range(0, day):
                c = Contribution.objects.create(addon_id=self.app.pk,
                                                user=user,
                                                amount='0.99',
                                                price_tier=price_tier,
                                                type=amo.CONTRIB_PURCHASE)
                c.update(created=datetime.datetime(2012, 5, day, 0, 0, 0))
        tasks.index_finance_daily(Contribution.objects.all())
        self.refresh(timesleep=1)

    def test_basic(self):
        """
        Check a sale (count) is found for each day in the expected range.
        """
        d_range = (datetime.date(2012, 05, 01), datetime.date(2012, 05, 15))
        stats = list(get_series_line(Contribution, 'day', addon=self.app.pk,
                                     date__range=d_range))
        dates_with_sales = [c['date'] for c in stats if c['count'] > 0]
        days = [d.day for d in dates_with_sales]
        for day in self.expected_days:
            eq_(day in days, True)

    def test_desc_order(self):
        """
        Check the returned data is in descending order by date.
        """
        d_range = (datetime.date(2012, 05, 01), datetime.date(2012, 05, 15))
        stats = list(get_series_line(Contribution, 'day', addon=self.app.pk,
                                     date__range=d_range))
        eq_(stats, sorted(stats, key=lambda x: x['date'], reverse=True))

    def test_revenue(self):
        """
        Check each day's revenue is correct.
        """
        d_range = (datetime.date(2012, 05, 01), datetime.date(2012, 05, 05))
        stats = list(get_series_line(Contribution, 'day',
                                     primary_field='revenue',
                                     addon=self.app.pk,
                                     date__range=d_range))

        for stat, day in zip(stats, sorted(self.expected_days, reverse=True)):
            expected_revenue = day * .99
            eq_(round(stat['count'], 2), round(expected_revenue, 2))


class TestGetSeriesColumn(amo.tests.ESTestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        super(TestGetSeriesColumn, self).setUp()
        # Create apps and contributions to index.
        self.app = amo.tests.app_factory()
        self.user = UserProfile.objects.get(username='regularuser')
        price_tier = Price.objects.create(price='0.99')

        # Create some revenue for several different currencies.
        self.expected = [
            {'currency': 'CAD', 'count': 0},
            {'currency': 'EUR', 'count': 0},
            {'currency': 'USD', 'count': 0}
        ]
        for expected in self.expected:
            for x in range(random.randint(1, 4)):
                # Amount doesn't matter for this stat since based off of price
                # tier (USD normalized).
                Contribution.objects.create(addon_id=self.app.pk,
                                            user=self.user,
                                            amount=random.randint(0, 10),
                                            currency=expected['currency'],
                                            price_tier=price_tier)
                expected['count'] += Decimal(price_tier.price)
            expected['count'] = int(expected['count'])
        tasks.index_finance_total_by_currency([self.app.pk])
        self.refresh(timesleep=1)

    def test_basic_revenue(self):
        stats = list(get_series_column(Contribution, addon=self.app.pk,
                                       primary_field='revenue',
                                       category_field='currency'))

        for stat in stats:
            stat['currency'] = stat['currency'].upper()
            stat['count'] = int(stat['count'])
        stats = sorted(stats, key=lambda stat: stat['currency'])
        eq_(stats, self.expected)

    def test_desc_order(self):
        stats = list(get_series_column(Contribution, addon=self.app.pk,
                                       primary_field='revenue',
                                       category_field='currency'))
        for stat in stats:
            stat['count'] = int(stat['count'])
        eq_(stats, sorted(stats, key=lambda stat: stat['count'], reverse=True))


class TestPadMissingStats(amo.tests.ESTestCase):

    def test_basic(self):
        days = [datetime.date(2012, 4, 29), datetime.date(2012, 5, 1),
                datetime.date(2012, 5, 3), datetime.date(2012, 5, 5)]
        expected_days = [datetime.date(2012, 4, 30), datetime.date(2012, 5, 2),
                         datetime.date(2012, 5, 4)]

        dummies = pad_missing_stats(days, 'day')
        days = [dummy['date'].date() for dummy in dummies]
        for day in expected_days:
            eq_(day in days, True)

    def test_with_date_range(self):
        date_range = (datetime.date(2012, 5, 1), datetime.date(2012, 5, 5))

        days = [datetime.date(2012, 5, 3)]
        expected_days = [datetime.date(2012, 5, 2), datetime.date(2012, 5, 4)]

        dummies = pad_missing_stats(days, 'day', date_range=date_range)
        days = [dummy['date'].date() for dummy in dummies]
        for day in expected_days:
            eq_(day in days, True)

    def test_with_fields(self):
        fields = ['test_field', 'fest_tield']

        days = [datetime.date(2012, 5, 1), datetime.date(2012, 5, 3)]
        dummies = pad_missing_stats(days, 'day', fields=fields)
        for dummy in dummies:
            for field in fields:
                eq_(field in dummy, True)

    def test_group_week(self):
        days = [datetime.date(2012, 5, 1), datetime.date(2012, 5, 15)]
        expected_days = [datetime.date(2012, 5, 8)]

        dummies = pad_missing_stats(days, 'week')
        days = [dummy['date'].date() for dummy in dummies]
        for day in expected_days:
            eq_(day in days, True)

    def test_group_month(self):
        days = [datetime.date(2012, 5, 1), datetime.date(2012, 7, 1)]
        expected_days = [datetime.date(2012, 6, 1)]

        dummies = pad_missing_stats(days, 'month')
        days = [dummy['date'].date() for dummy in dummies]
        for day in expected_days:
            eq_(day in days, True)


class TestOverall(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        self.keys = ['apps_count_new', 'apps_count_installed',
                     'apps_review_count_new']

    def test_url(self):
        self.assert3xx(self.client.get(reverse('mkt.stats.overall')),
                       reverse('mkt.stats.apps_count_new'))

    def get_url(self, name):
        return (reverse('mkt.stats.%s' % name) +
                '/%s-day-20090601-20090630.json' % name)

    def test_stats(self):
        for stat in self.keys:
            GlobalStat.objects.create(name=stat, count=1,
                                      date=datetime.date(2009, 06, 12))

        for stat in self.keys:
            res = self.client.get(self.get_url(stat))
            content = json.loads(res.content)
            eq_(content[0]['date'], '2009-06-12')
            eq_(content[0]['count'], 1)

    def test_stats_view_perm(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        res = self.client.get(reverse('mkt.stats.apps_count_new'))
        eq_(res.status_code, 403)

        self.grant_permission(
            UserProfile.objects.get(username='regularuser'), 'Stats:View')
        res = self.client.get(reverse('mkt.stats.apps_count_new'))
        eq_(res.status_code, 200)
