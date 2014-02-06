from nose.tools import eq_

import amo
import amo.tests
from mkt.submit.models import AppSubmissionChecklist
from mkt.webapps.models import Webapp

from mkt.site.fixtures import fixture

class TestAppSubmissionChecklist(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp)

    def test_default(self):
        eq_(self.cl.get_completed(), [])

    def test_terms(self):
        self.cl.update(terms=True)
        eq_(self.cl.get_completed(), ['terms'])

    def test_manifest(self):
        self.cl.update(terms=True, manifest=True)
        eq_(self.cl.get_completed(), ['terms', 'manifest'])

    def test_details(self):
        self.cl.update(terms=True, manifest=True, details=True)
        eq_(self.cl.get_completed(), ['terms', 'manifest', 'details'])

    def test_next_details(self):
        self.cl.update(terms=True, manifest=True)
        eq_(self.cl.get_next(), 'details')
