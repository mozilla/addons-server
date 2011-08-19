from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests

from webapps.models import Webapp


class TestDetail(amo.tests.TestCase):

    def setUp(self):
        self.webapp = Webapp(name='woo', app_slug='yeah')
        self.webapp.save()

    def test_more_url(self):
        response = self.client.get(self.webapp.get_url_path())
        eq_(pq(response.content)('#more-webpage').attr('data-more-url'),
            self.webapp.get_url_path(more=True))
