import datetime
import random

from nose.tools import eq_

import amo
import amo.tests
from market.models import Refund
from mkt.stats import tasks
from mkt.inapp_pay.models import InappConfig, InappPayment
from stats.models import Contribution


class TestIndexFinanceTotal(amo.tests.ESTestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()

        self.expected = {'revenue': 0, 'count': 5, 'refunds': 2}
        for x in range(self.expected['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                amount=str(random.randint(0, 10) + .99))
            self.expected['revenue'] += c.amount

            # Create 2 refunds.
            if x % 2 == 1:
                Refund.objects.create(contribution=c,
                                      status=amo.REFUND_APPROVED)
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


class TestIndexFinanceTotalBySrc(amo.tests.ESTestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()

        self.sources = ['home', 'search', 'featured']
        self.expected = {
            'home': {'revenue': 0, 'count': 2, 'refunds': 1},
            'search': {'revenue': 0, 'count': 3, 'refunds': 1},
            'featured': {'revenue': 0, 'count': 4, 'refunds': 1}
        }
        for source in self.sources:
            # Create sales.
            for x in range(self.expected[source]['count']):
                c = Contribution.objects.create(addon_id=self.app.pk,
                    source=source, amount=str(random.randint(0, 10) + .99))
                self.expected[source]['revenue'] += c.amount
            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
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


class TestIndexFinanceTotalByCurrency(amo.tests.ESTestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()

        self.currencies = ['CAD', 'USD', 'EUR']
        self.expected = {
            'CAD': {'revenue': 0, 'count': 3, 'refunds': 1},
            'USD': {'revenue': 0, 'count': 4, 'refunds': 1},
            'EUR': {'revenue': 0, 'count': 2, 'refunds': 1}
        }
        for currency in self.currencies:
            # Create sales.
            for x in range(self.expected[currency]['count']):
                c = Contribution.objects.create(addon_id=self.app.pk,
                    currency=currency, amount=str(random.randint(0, 10) + .99))
                self.expected[currency]['revenue'] += c.amount
            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_by_currency([self.app.pk])
        self.refresh(timesleep=1)

        # Grab document for each source breakdown and compare.
        for currency in self.currencies:
            # For some reason, query fails if uppercase letter in filter.
            document = (Contribution.search().filter(addon=self.app.pk,
                        currency=currency.lower()).values_dict('currency',
                        'revenue', 'count', 'refunds')[0])
            document = {'count': document['count'],
                        'revenue': int(document['revenue']),
                        'refunds': document['refunds']}
            self.expected[currency]['revenue'] = (
                int(self.expected[currency]['revenue'])
            )
            eq_(document, self.expected[currency])


class TestIndexFinanceDaily(amo.tests.ESTestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()

        self.ids = []
        self.expected = {'date': datetime.datetime.today(),
                         'revenue': 0, 'count': 5, 'refunds': 2}
        for x in range(self.expected['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                amount=str(random.randint(0, 10) + .99),
                type=amo.CONTRIB_PURCHASE)
            self.expected['revenue'] += c.amount
            self.ids.append(c.id)

            # Create 2 refunds.
            if x % 2 == 1:
                c.uuid = 123
                c.save()
                Refund.objects.create(contribution=c,
                                      status=amo.REFUND_APPROVED)

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


class TestIndexFinanceTotalInapp(amo.tests.ESTestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()
        self.inapp = InappConfig.objects.create(addon=self.app,
                                                public_key='asd')

        self.expected = {'revenue': 0, 'count': 5, 'refunds': 2}
        for x in range(self.expected['count']):
            c = Contribution.objects.create(addon_id=self.app.pk,
                amount=str(random.randint(0, 10) + .99))
            InappPayment.objects.create(config=self.inapp, contribution=c)
            self.expected['revenue'] += c.amount

            # Create 2 refunds.
            if x % 2 == 1:
                Refund.objects.create(contribution=c,
                                      status=amo.REFUND_APPROVED)
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_inapp([self.app.pk])
        self.refresh(timesleep=1)

        document = (InappPayment.search().
                    filter(addon=self.app.pk, inapp=self.inapp.pk).
                    values_dict('revenue', 'count', 'refunds'))[0]

        document = {'count': document['count'],
                    'revenue': int(document['revenue']),
                    'refunds': document['refunds']}
        self.expected['revenue'] = int(self.expected['revenue'])

        eq_(document, self.expected)


class TestIndexFinanceTotalInappByCurrency(amo.tests.ESTestCase):

    def setUp(self):
        self.app = amo.tests.app_factory()
        self.inapp = InappConfig.objects.create(addon=self.app,
                                                public_key='asd')

        self.currencies = ['CAD', 'USD', 'EUR']
        self.expected = {
            'CAD': {'revenue': 0, 'count': 3, 'refunds': 1},
            'USD': {'revenue': 0, 'count': 4, 'refunds': 1},
            'EUR': {'revenue': 0, 'count': 2, 'refunds': 1}
        }
        for currency in self.currencies:
            # Create sales.
            for x in range(self.expected[currency]['count']):
                c = Contribution.objects.create(addon_id=self.app.pk,
                    currency=currency, amount=str(random.randint(0, 10) + .99))
                InappPayment.objects.create(config=self.inapp, contribution=c)
                self.expected[currency]['revenue'] += c.amount
            # Create refunds.
            Refund.objects.create(contribution=c,
                                  status=amo.REFUND_APPROVED)
        self.refresh()

    def test_index(self):
        tasks.index_finance_total_inapp_by_currency([self.app.pk])
        self.refresh(timesleep=1)

        # Grab document for each source breakdown and compare.
        for currency in self.currencies:
            # For some reason, query fails if uppercase letter in filter.
            document = (InappPayment.search().
                        filter(addon=self.app.pk, inapp=self.inapp.pk,
                               currency=currency.lower()).
                        values_dict('currency', 'revenue', 'count',
                                    'refunds'))[0]
            document = {'count': document['count'],
                        'revenue': int(document['revenue']),
                        'refunds': document['refunds']}
            self.expected[currency]['revenue'] = (
                int(self.expected[currency]['revenue'])
            )
            eq_(document, self.expected[currency])
