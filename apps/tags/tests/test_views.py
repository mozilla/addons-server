from nose.tools import eq_

from pyquery import PyQuery as pq
import test_utils

from addons.models import Addon
from tags.models import TagStat

from django.core.urlresolvers import reverse, NoReverseMatch


class TestManagement(test_utils.TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json']

    def test_tags_details_view(self):
        """Test that there are some tags being shown on the details page."""
        url = reverse('addons.detail', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(len(doc('li.tag')), 4)
        assert 'Tags' in [d.text for d in doc('h3')]


class TestXSS(test_utils.TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json']

    xss = "<script src='foo.bar'>"

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.tag = self.addon.tags.all()[0]
        self.tag.tag_text = self.xss
        self.tag.save()
        TagStat.objects.create(tag=self.tag, num_addons=1)

    def test_tags_xss_detail(self):
        """Test xss tag detail."""
        url = reverse('addons.detail', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(doc('li.tag')[0].text_content().strip(), self.xss)

    def test_tags_xss_home(self):
        """Test xss tag home."""
        url = reverse('home')
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(doc('a.tag')[0].text_content().strip(), self.xss)

    def test_tags_xss_cloud(self):
        """Test xss tag cloud."""
        url = reverse('tags.top_cloud')
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(doc('a.tag')[0].text_content().strip(), self.xss)


class TestXSSURLFail(test_utils.TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json']

    xss = "<script>alert('xss')</script>"

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.tag = self.addon.tags.all()[0]
        self.tag.tag_text = self.xss
        self.tag.save()
        TagStat.objects.create(tag=self.tag, num_addons=1)

    def test_tags_xss(self):
        """Test xss tag detail."""
        url = reverse('addons.detail', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        eq_(doc('li.tag')[0].text_content().strip(), self.xss)

    def test_tags_xss_home(self):
        """Test xss tag home."""
        self.assertRaises(NoReverseMatch, reverse,
                          'tags.detail', args=[self.xss])

    def test_tags_xss_cloud(self):
        """Test xss tag cloud."""
        self.assertRaises(NoReverseMatch, reverse,
                          'tags.top_cloud', args=[self.xss])


class TestNoTags(test_utils.TestCase):
    fixtures = ['base/addon_3615']

    def test_tags_no_details_view(self):
        """Test that there is no tag header tags being shown."""
        url = reverse('addons.detail', args=['a3615'])
        r = self.client.get(url)
        doc = pq(r.content)
        assert 'Tags' not in [d.text for d in doc('h3')]
