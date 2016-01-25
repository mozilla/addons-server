import datetime
import os

from django.conf import settings


import amo.tests
from addons.models import Addon
from devhub.cron import update_blog_posts
from devhub.tasks import convert_purified
from devhub.models import BlogPost


class TestRSS(amo.tests.TestCase):

    def test_rss_cron(self):
        url = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                           'rss_feeds', 'blog.xml')

        settings.DEVELOPER_BLOG_URL = url

        update_blog_posts()
        assert BlogPost.objects.count() == 5

        bp = BlogPost.objects.all()[0]
        url = ("http://blog.mozilla.com/addons/2011/06/10/"
               "update-in-time-for-thunderbird-5/")
        assert bp.title == 'Test!'
        assert bp.date_posted == datetime.date(2011, 6, 10)
        assert bp.permalink == url


class TestPurify(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestPurify, self).setUp()
        self.addon = Addon.objects.get(pk=3615)

    def test_no_html(self):
        self.addon.the_reason = 'foo'
        self.addon.save()
        last = Addon.objects.get(pk=3615).modified
        convert_purified([self.addon.pk])
        addon = Addon.objects.get(pk=3615)
        assert addon.modified == last

    def test_has_html(self):
        self.addon.the_reason = 'foo <script>foo</script>'
        self.addon.save()
        convert_purified([self.addon.pk])
        addon = Addon.objects.get(pk=3615)
        assert addon.the_reason.localized_string_clean
