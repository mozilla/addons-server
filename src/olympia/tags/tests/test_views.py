from django.urls import NoReverseMatch, reverse

from pyquery import PyQuery as pq

from olympia.addons.models import Addon
from olympia.amo.tests import TestCase


class TestManagement(TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json']

    def test_tags_details_view(self):
        """Test that there are some tags being shown on the details page."""
        url = reverse('addons.detail_more', args=['a3615'])
        r = self.client.get_ajax(url, follow=True)
        doc = pq(r.content)
        assert len(doc('li.tag')) == 4
        assert 'Tags' in [d.text for d in doc('h3')]


class TestXSS(TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json']

    xss = "<script src='foo.bar'>"
    escaped = "&lt;script src=&#39;foo.bar&#39;&gt;"

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.tag = self.addon.tags.all()[0]
        self.tag.tag_text = self.xss
        self.tag.num_addons = 1
        self.tag.save()

    def test_tags_xss_detail(self):
        """Test xss tag detail."""
        url = reverse('addons.detail_more', args=['a3615'])
        r = self.client.get_ajax(url, follow=True)
        assert self.escaped in r.content
        assert self.xss not in r.content


class TestXSSURLFail(TestCase):
    fixtures = ['base/addon_3615',
                'tags/tags.json']

    xss = "<script>alert('xss')</script>"
    escaped = "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;"

    def setUp(self):
        self.addon = Addon.objects.get(pk=3615)
        self.tag = self.addon.tags.all()[0]
        self.tag.tag_text = self.xss
        self.tag.num_addons = 1
        self.tag.save()

    def test_tags_xss(self):
        """Test xss tag detail."""
        url = reverse('addons.detail_more', args=['a3615'])
        r = self.client.get_ajax(url, follow=True)
        assert self.escaped in r.content
        assert self.xss not in r.content

    def test_tags_xss_home(self):
        """Test xss tag home."""
        self.assertRaises(NoReverseMatch, reverse,
                          'tags.detail', args=[self.xss])

    def test_no_reverse(self):
        assert not self.tag.can_reverse()


class TestNoTags(TestCase):
    fixtures = ['base/addon_3615']

    def test_tags_no_details_view(self):
        """Test that there is no tag header tags being shown."""
        url = reverse('addons.detail', args=['a3615'])
        r = self.client.get(url, follow=True)
        doc = pq(r.content)
        assert 'Tags' not in [d.text for d in doc('h3')]
