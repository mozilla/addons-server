import datetime
from decimal import Decimal
import random

from django.utils import unittest

from nose.tools import eq_

import amo
import amo.tests
from market.models import Refund, Price
from mkt.stats import tasks
from mkt.stats.search import cut
from mkt.inapp_pay.models import InappConfig, InappPayment
from stats.models import Contribution
from users.models import UserProfile


class BaseTaskTest(amo.tests.ESTestCase):
    fixtures = ['base/users']

    def baseSetUp(self):
        self.app = amo.tests.app_factory()
        self.usd_price = '0.99'
        self.price_tier = Price.objects.create(price=self.usd_price)

        self.inapp = InappConfig.objects.create(
            addon=self.app, public_key='asd')
        self.inapp_name = 'test'
        self.user = UserProfile.objects.get(username='regularuser')


class TestIndexFinanceTotal(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.expected = {'revenue': 0, 'count': 5, 'refunds': 2}
        for x in range(self.expected['count']):
            c = Contribution.objects.create(
                user=self.user,
                addon_id=self.app.pk,
                type=amo.CONTRIB_PURCHASE,
                amount=str(random.randint(0, 10) + .99),
                price_tier=self.price_tier)
            self.expected['revenue'] += cut(self.usd_price)

            # Create 2 refunds.
            if x % 2 == 1:
                Refund.objects.create(contribution=c,
                                      status=amo.REFUND_APPROVED)
                self.expected['revenue'] -= cut(self.usd_price)
                self.expected['count'] -= 1
        self.refresh()

    def test_index(self):
        tasks.index_finance_total([self.app.pk])
        self.refresh(timesleep=1)

        document = Contribution.search().filter(addon=self.app.pk
            ).values_dict('revenue', 'count', 'refunds')[0]

        document = {'count': document['count'],
                    'revenue': int(document['revenue']),
                    'refunds': document['refunds']}
        self.expected['revenue'] = int(self.expected['revenue'])

        eq_(document, self.expected)


class TestIndexFinanceTotalBySrc(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.sources = ['mkt-home', 'front-search', 'featured']
        self.expected = {
            'mkt-home': {'revenue': 0, 'count': 2, 'refunds': 1},
            'front-search': {'revenue': 0, 'count': 3, 'refunds': 1},
            'featured': {'revenue': 0, 'count': 4, 'refunds': 1}
        }
        for source in self.sources:
            # Create sales.
            for x in range(self.expected[source]['count']):
                c = Contribution.objects.create(
                    user=self.user,
                    addon_id=self.app.pk, source=source,
                    type=amo.CONTRIB_PURCHASE,
                    amount=str(random.randint(0, 10) + .99),
                    price_tier=self.price_tier)
                self.expected[source]['revenue'] += cut(self.usd_price)

            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
            self.expected[source]['revenue'] -= cut(self.usd_price)
            self.expected[source]['count'] -= 1
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_by_src([self.app.pk])
        self.refresh(timesleep=1)

        # Grab document for each source breakdown and compare.
        for source in self.sources:
            # For some reason, query fails if uppercase letter in filter.
            document = (Contribution.search().filter(addon=self.app.pk,
                        source=source.lower()).values_dict('source', 'revenue',
                        'count', 'refunds')[0])
            document = {'count': document['count'],
                        'revenue': int(document['revenue']),
                        'refunds': document['refunds']}
            self.expected[source]['revenue'] = (
                int(self.expected[source]['revenue'])
            )
            eq_(document, self.expected[source])


class TestIndexFinanceTotalByCurrency(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.currencies = ['CAD', 'USD', 'EUR']
        self.expected = {
            'CAD': {'revenue': 0, 'count': 3, 'refunds': 1,
                    'revenue_non_normalized': 0},
            'USD': {'revenue': 0, 'count': 4, 'refunds': 1,
                    'revenue_non_normalized': 0},
            'EUR': {'revenue': 0, 'count': 2, 'refunds': 1,
                    'revenue_non_normalized': 0}
        }
        for currency in self.currencies:
            # Create sales.
            for x in range(self.expected[currency]['count']):
                amount = str(random.randint(0, 10))
                c = Contribution.objects.create(addon_id=self.app.pk,
                    user=self.user,
                    type=amo.CONTRIB_PURCHASE,
                    currency=currency,
                    amount=amount,
                    price_tier=self.price_tier)
                self.expected[currency]['revenue'] += cut(self.usd_price)
                self.expected[currency]['revenue_non_normalized'] += cut(
                    amount)

            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
            self.expected[currency]['revenue'] -= cut(self.usd_price)
            self.expected[currency]['revenue_non_normalized'] -= cut(amount)
            self.expected[currency]['count'] -= 1
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_by_currency([self.app.pk])
        self.refresh(timesleep=1)

        # Grab document for each source breakdown and compare.
        for currency in self.currencies:
            # For some reason, query fails if uppercase letter in filter.
            document = (Contribution.search().filter(addon=self.app.pk,
                        currency=currency.lower()).values_dict('currency',
                        'revenue', 'count', 'refunds',
                        'revenue_non_normalized')[0])
            document = {
                'count': document['count'],
                'revenue': int(document['revenue']),
                'refunds': document['refunds'],
                'revenue_non_normalized':
                    int(document['revenue_non_normalized'])}
            self.expected[currency]['revenue'] = (
                int(self.expected[currency]['revenue'])
            )
            self.expected[currency]['revenue_non_normalized'] = (
                int(self.expected[currency]['revenue_non_normalized'])
            )
            eq_(document, self.expected[currency])


class TestIndexFinanceDaily(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.ids = []
        self.expected = {'date': datetime.datetime.today(),
                         'revenue': 0, 'count': 5, 'refunds': 2}
        for x in range(self.expected['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                self.user=user,
                type=amo.CONTRIB_PURCHASE,
                amount=str(random.randint(0, 10) + .99),
                price_tier=self.price_tier)
            self.expected['revenue'] += cut(self.usd_price)
            self.ids.append(c.id)

            # Create 2 refunds.
            if x % 2 == 1:
                c.uuid = 123
                c.save()
                Refund.objects.create(contribution=c,
                                      status=amo.REFUND_APPROVED)
                self.expected['revenue'] -= cut(self.usd_price)
                self.expected['count'] -= 1

    def test_index(self):
        tasks.index_finance_daily.delay(self.ids)
        self.refresh(timesleep=1)

        document = Contribution.search().filter(addon=self.app.pk
            ).values_dict('date', 'revenue', 'count', 'refunds')[0]

        date = document['date']
        ex_date = self.expected['date']
        eq_((date.year, date.month, date.day),
            (ex_date.year, ex_date.month, ex_date.day))

        document = {'count': document['count'],
                    'revenue': int(document['revenue']),
                    'refunds': document['refunds']}
        del(self.expected['date'])

        self.expected['revenue'] = int(self.expected['revenue'])
        eq_(document, self.expected)


class TestIndexFinanceTotalInapp(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.expected = {
            self.inapp_name: {'revenue': 0, 'count': 5, 'refunds': 2}
        }
        self.expected_inapp = self.expected[self.inapp_name]

        for x in range(self.expected[self.inapp_name]['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                user=self.user,
                type=amo.CONTRIB_PURCHASE,
                amount=str(random.randint(0, 10) + .99),
                price_tier=self.price_tier)

            InappPayment.objects.create(config=self.inapp, contribution=c,
                                        name=self.inapp_name)

            self.expected_inapp['revenue'] += cut(self.usd_price)

            # Create 2 refunds.
            if x % 2 == 1:
                Refund.objects.create(contribution=c,
                                      status=amo.REFUND_APPROVED)
                self.expected_inapp['revenue'] -= cut(self.usd_price)
                self.expected_inapp['count'] -= 1
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_inapp([self.app.pk])
        self.refresh(timesleep=1)

        document = (InappPayment.search().
                    filter(addon=self.app.pk, inapp=self.inapp_name).
                    values_dict('revenue', 'count', 'refunds'))[0]

        document = {'count': document['count'],
                    'revenue': int(document['revenue']),
                    'refunds': document['refunds']}
        self.expected[self.inapp_name]['revenue'] = int(
            self.expected[self.inapp_name]['revenue'])

        eq_(document, self.expected[self.inapp_name])


class TestIndexFinanceTotalInappByCurrency(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.currencies = ['CAD', 'USD', 'EUR']
        self.expected = {
            self.inapp_name: {
                'CAD': {'revenue': 0, 'count': 3, 'refunds': 1,
                        'revenue_non_normalized': 0},
                'USD': {'revenue': 0, 'count': 4, 'refunds': 1,
                        'revenue_non_normalized': 0},
                'EUR': {'revenue': 0, 'count': 2, 'refunds': 1,
                        'revenue_non_normalized': 0}
            }
        }
        expected_inapp = self.expected[self.inapp_name]

        for currency in self.currencies:
            # Create sales.
            for x in range(self.expected[self.inapp_name][currency]['count']):
                amount = str(random.randint(0, 10))
                c = Contribution.objects.create(addon_id=self.app.pk,
                    user=self.user,
                    type=amo.CONTRIB_PURCHASE,
                    currency=currency,
                    amount=amount,
                    price_tier=self.price_tier)

                InappPayment.objects.create(config=self.inapp, contribution=c,
                                            name=self.inapp_name)

                expected_inapp_curr = expected_inapp[currency]
                expected_inapp_curr['revenue'] += cut(self.usd_price)
                expected_inapp_curr['revenue_non_normalized'] += cut(amount)

            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
            expected_inapp[currency]['revenue'] -= cut(self.usd_price)
            expected_inapp[currency]['revenue_non_normalized'] -= cut(amount)
            self.expected[self.inapp_name][currency]['count'] -= 1

        self.refresh()

    def test_index(self):
        tasks.index_finance_total_inapp_by_currency([self.app.pk])
        self.refresh(timesleep=1)

        # Grab document for each source breakdown and compare.
        for currency in self.currencies:
            # For some reason, query fails if uppercase letter in filter.
            document = (InappPayment.search().
                        filter(addon=self.app.pk, inapp=self.inapp_name,
                               currency=currency.lower()).
                        values_dict('currency', 'revenue', 'count',
                                    'refunds',
                                    'revenue_non_normalized'))[0]
            document = {'count': document['count'],
                        'revenue': int(document['revenue']),
                        'refunds': document['refunds'],
                        'revenue_non_normalized':
                            int(document['revenue_non_normalized'])}

            expected_inapp = self.expected[self.inapp_name]
            expected_inapp[currency]['revenue'] = (
                int(expected_inapp[currency]['revenue'])
            )
            expected_inapp[currency]['revenue_non_normalized'] = (
                int(expected_inapp[currency]['revenue_non_normalized'])
            )
            eq_(document, expected_inapp[currency])


class TestIndexFinanceTotalInappBySource(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.sources = ['home', 'mkt-search', 'FEATURED']
        self.expected = {
            self.inapp_name: {
                self.sources[0]: {'revenue': 0, 'count': 3, 'refunds': 1},
                self.sources[1]: {'revenue': 0, 'count': 4, 'refunds': 1},
                self.sources[2]: {'revenue': 0, 'count': 2, 'refunds': 1}
            }
        }
        self.expected_inapp = self.expected[self.inapp_name]

        for source in self.sources:
            # Create sales.
            for x in range(self.expected_inapp[source]['count']):
                c = Contribution.objects.create(addon_id=self.app.pk,
                    user=self.user,
                    type=amo.CONTRIB_PURCHASE,
                    source=source,
                    amount=str(random.randint(0, 10) + .99),
                    price_tier=self.price_tier)
                InappPayment.objects.create(config=self.inapp, contribution=c,
                                            name=self.inapp_name)
                self.expected_inapp[source]['revenue'] += cut(self.usd_price)

            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
            self.expected_inapp[source]['revenue'] -= cut(self.usd_price)
            self.expected_inapp[source]['count'] -= 1
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_inapp_by_src([self.app.pk])
        self.refresh(timesleep=1)

        # Grab document for each source breakdown and compare.
        for source in self.sources:
            # For some reason, query fails if uppercase letter in filter.
            document = (InappPayment.search().
                        filter(addon=self.app.pk, inapp=self.inapp_name,
                               source=source.lower()).
                        values_dict('source', 'revenue', 'count',
                                    'refunds'))[0]
            document = {'count': document['count'],
                        'revenue': int(document['revenue']),
                        'refunds': document['refunds']}
            self.expected_inapp[source]['revenue'] = (
                int(self.expected_inapp[source]['revenue'])
            )
            eq_(document, self.expected_inapp[source])


class TestIndexFinanceDailyInapp(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        self.c_ids = []
        self.ids = []
        self.expected = {
            self.inapp_name: {
                'date': datetime.datetime.today(),
                'revenue': 0, 'count': 5, 'refunds': 2
            }
        }
        for x in range(self.expected[self.inapp_name]['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                    user=self.user,
                    type=amo.CONTRIB_PURCHASE,
                    amount=str(random.randint(0, 10) + .99),
                    price_tier=self.price_tier)
            self.c_ids.append(c.id)
            i = InappPayment.objects.create(config=self.inapp, contribution=c,
                                            name=self.inapp_name)
            self.expected[self.inapp_name]['revenue'] += cut(self.usd_price)
            self.ids.append(i.id)

        for x in range(self.expected[self.inapp_name]['refunds']):
            c = Contribution.objects.get(id=self.c_ids[x])
            c.update(uuid=123)
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
            self.expected[self.inapp_name]['revenue'] -= cut(self.usd_price)
            self.expected[self.inapp_name]['count'] -= 1

    def test_index(self):
        tasks.index_finance_daily_inapp.delay(self.ids)
        self.refresh(timesleep=1)

        document = InappPayment.search().filter(config__addon=self.app.pk
            ).values_dict('date', 'inapp', 'revenue', 'count', 'refunds')[0]

        eq_(self.inapp_name, document['inapp'])

        date = document['date']
        ex_date = self.expected[self.inapp_name]['date']
        eq_((date.year, date.month, date.day),
            (ex_date.year, ex_date.month, ex_date.day))

        document = {
            self.inapp_name: {
                    'count': document['count'],
                    'revenue': int(document['revenue']),
                    'refunds': document['refunds']
            }
        }
        del(self.expected[self.inapp_name]['date'])

        self.expected[self.inapp_name]['revenue'] = (
            int(self.expected[self.inapp_name]['revenue']))
        eq_(document, self.expected)


class TestAlreadyIndexed(BaseTaskTest):

    def setUp(self):
        self.baseSetUp()

        today = datetime.datetime.today()
        date = datetime.datetime(today.year, today.month, today.day)

        self.ids = []
        self.expected = {'addon': self.app.pk,
                         'date': date,
                         'revenue': Decimal('0'), 'count': 3,
                         'refunds': 1}

        for x in range(self.expected['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                user=self.user,
                type=amo.CONTRIB_PURCHASE,
                amount=str(random.randint(0, 10)),
                price_tier=self.price_tier)
            self.refresh(timesleep=1)
            self.ids.append(c.id)
            self.expected['revenue'] += Decimal(self.usd_price)

        c.update(uuid=123)
        Refund.objects.create(contribution=c,
                              status=amo.REFUND_APPROVED)
        self.expected['revenue'] -= Decimal(self.usd_price)
        self.expected['count'] -= 1

        self.expected['revenue'] = cut(self.expected['revenue'])

    def test_basic(self):
        eq_(tasks.already_indexed(Contribution, self.expected), [])
        tasks.index_finance_daily.delay(self.ids)
        self.refresh(timesleep=1)
        eq_(tasks.already_indexed(Contribution, self.expected) != [], True)


class TestCut(unittest.TestCase):

    def test_basic(self):
        eq_(cut(0), Decimal(str(0)))
        eq_(cut(1), Decimal(str(.7)))
        eq_(cut(10), Decimal(str(7)))
        eq_(cut(33), Decimal(str(23.10)))
