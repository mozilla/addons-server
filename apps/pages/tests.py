from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse


class TestPages(amo.tests.TestCase):

    def _check(self, url, status):
        resp = self.client.get(reverse(url))
        eq_(resp.status_code, status)

    def test_status(self):
        pages = ['pages.about', 'pages.credits', 'pages.faq',
                 'pages.acr_firstrun', 'pages.dev_faq', 'pages.review_guide',
                 'pages.sunbird']
        for page in pages:
            self._check(page, 200)
