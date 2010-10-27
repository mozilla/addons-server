from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from amo.urlresolvers import reverse


class TestManagement(test_utils.TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json', ]

    def test_tags_details_view(self):
        """Test that there are some tags being shown on the details page"""
        url = reverse('addons.detail', args=[3615, ])
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(len(doc('li.tag')), 4)
