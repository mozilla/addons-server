from nose.tools import eq_

import amo
import amo.tests
from mkt.submit.models import AppSubmissionChecklist
from webapps.models import Webapp


class TestAppSubmissionChecklist(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.cl = AppSubmissionChecklist.objects.create(addon=self.webapp)

    def test_default(self):
        eq_(self.cl.get_completed(), [])

    def test_terms(self):
        self.cl.terms = True
        self.cl.save()
        eq_(self.cl.get_completed(), ['terms'])

    def test_manifest(self):
        self.cl.terms = True
        self.cl.manifest = True
        self.cl.save()
        eq_(self.cl.get_completed(), ['terms', 'manifest'])

    def test_details(self):
        self.cl.terms = True
        self.cl.manifest = True
        self.cl.details = True
        self.cl.save()
        eq_(self.cl.get_completed(), ['terms', 'manifest', 'details'])

    def test_payments(self):
        self.cl.terms = True
        self.cl.manifest = True
        self.cl.details = True
        self.cl.payments = True
        self.cl.save()
        eq_(self.cl.get_completed(),
            ['terms', 'manifest', 'details', 'payments'])

    def test_skipped_details(self):
        self.cl.terms = True
        self.cl.manifest = True
        self.cl.payments = True
        self.cl.save()
        eq_(self.cl.get_completed(), ['terms', 'manifest', 'payments'])
