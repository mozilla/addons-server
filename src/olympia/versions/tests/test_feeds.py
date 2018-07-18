# -*- coding: utf-8 -*-
import mock

from pyquery import PyQuery

from olympia.amo.tests import TestCase
from olympia.amo.urlresolvers import reverse
from olympia.versions import feeds


class TestFeeds(TestCase):
    fixtures = ['addons/eula+contrib-addon', 'addons/default-to-compat']
    rel_ns = {'atom': 'http://www.w3.org/2005/Atom'}

    def setUp(self):
        super(TestFeeds, self).setUp()
        patcher = mock.patch.object(feeds, 'PER_PAGE', 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_feed(self, slug, **kwargs):
        url = reverse('addons.versions.rss', args=[slug])
        r = self.client.get(url, kwargs, follow=True)
        return PyQuery(r.content, parser='xml')

    def test_feed_elements_present(self):
        """specific elements are present and reasonably well formed"""
        doc = self.get_feed('a11730')
        assert doc('rss channel title')[0].text == (
            'IPv6 Google Search Version History'
        )
        assert doc('rss channel link')[0].text.endswith('/en-US/firefox/')
        # assert <description> is present
        assert len(doc('rss channel description')[0].text) > 0
        # description doesn not contain the default object to string
        desc_elem = doc('rss channel description')[0]
        assert 'Content-Type:' not in desc_elem
        # title present
        assert len(doc('rss channel item title')[0].text) > 0
        # link present and well formed
        item_link = doc('rss channel item link')[0]
        assert item_link.text.endswith('/addon/a11730/versions/20090521')
        # guid present
        assert len(doc('rss channel item guid')[0].text) > 0
        # proper date format for item
        item_pubdate = doc('rss channel item pubDate')[0]
        assert item_pubdate.text == 'Thu, 21 May 2009 05:37:15 +0000'

    def assert_page_relations(self, doc, page_relations):
        rel = doc[0].xpath('//channel/atom:link', namespaces=self.rel_ns)
        relations = dict((link.get('rel'), link.get('href')) for link in rel)
        assert relations.pop('first').endswith('format:rss')

        assert len(relations) == len(page_relations)
        for rel, href in relations.iteritems():
            page = page_relations[rel]
            assert href.endswith(
                'format:rss' if page == 1 else 'format:rss?page=%s' % page
            )

    def test_feed_first_page(self):
        """first page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=1)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.3 - Dec. 5, 2011'
        )
        self.assert_page_relations(doc, {'self': 1, 'next': 2, 'last': 4})

    def test_feed_middle_page(self):
        """a middle page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=2)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.2 - Dec. 5, 2011'
        )
        self.assert_page_relations(
            doc, {'previous': 1, 'self': 2, 'next': 3, 'last': 4}
        )

    def test_feed_last_page(self):
        """last page has the right elements and page relations"""
        doc = self.get_feed('addon-337203', page=4)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.0 - Dec. 5, 2011'
        )
        self.assert_page_relations(doc, {'previous': 3, 'self': 4, 'last': 4})

    def test_feed_invalid_page(self):
        """an invalid page falls back to page 1"""
        doc = self.get_feed('addon-337203', page=5)
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.3 - Dec. 5, 2011'
        )

    def test_feed_no_page(self):
        """no page defaults to page 1"""
        doc = self.get_feed('addon-337203')
        assert doc('rss item title')[0].text == (
            'Addon for DTC 1.3 - Dec. 5, 2011'
        )
