import datetime
import random

from nose.tools import eq_

import amo
import amo.tests
from market.models import Refund
from mkt.stats import tasks
from stats.models import Contribution


class TestIndexAddonAggregateContributions(amo.tests.ESTestCase):

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
        tasks.index_addon_aggregate_contributions([self.app.pk])
        self.refresh(timesleep=1)

        document = Contribution.search().filter(addon=self.app.pk
            ).values_dict('revenue', 'count', 'refunds')[0]

        document['revenue'] = int(document['revenue'])
        self.expected['revenue'] = int(self.expected['revenue'])

        eq_(document, self.expected)


class TestIndexContributionCounts(amo.tests.ESTestCase):

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
        tasks.index_contribution_counts.delay(self.ids)
        self.refresh(timesleep=1)

        document = Contribution.search().filter(addon=self.app.pk
            ).values_dict('date', 'revenue', 'count', 'refunds')[0]

        date = document['date']
        ex_date = self.expected['date']
        eq_((date.year, date.month, date.day),
            (ex_date.year, ex_date.month, ex_date.day))
        del(document['date'])
        del(self.expected['date'])

        document['revenue'] = int(document['revenue'])
        self.expected['revenue'] = int(self.expected['revenue'])
        eq_(document, self.expected)
