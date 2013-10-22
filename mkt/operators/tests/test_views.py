from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from amo.tests import app_factory
from amo.urlresolvers import reverse
from users.models import UserProfile

from mkt.developers.models import PreloadTestPlan
from mkt.operators.views import preloads
from mkt.site.fixtures import fixture


class TestPreloadCandidates(amo.tests.TestCase):
    fixtures = fixture('user_operator')

    def setUp(self):
        self.create_switch('preload-apps')
        self.url = reverse('operators.preloads')
        self.user = UserProfile.objects.get()
        self.app = app_factory()

    def test_preloads(self):
        plan = PreloadTestPlan.objects.create(addon=self.app, filename='tstpn')

        req = amo.tests.req_factory_factory(self.url, user=self.user)
        res = preloads(req)
        eq_(res.status_code, 200)
        doc = pq(res.content)

        eq_(doc('tbody tr').length, 1)
        eq_(doc('td:last-child a').attr('href'),
            plan.preload_test_plan_url)
