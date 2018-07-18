import datetime
import os

from django.conf import settings

from olympia.amo.tests import TestCase
from olympia.devhub.cron import update_blog_posts
from olympia.devhub.models import BlogPost


class TestRSS(TestCase):
    def test_rss_cron(self):
        url = os.path.join(
            settings.ROOT,
            'src',
            'olympia',
            'devhub',
            'tests',
            'rss_feeds',
            'blog.xml',
        )

        settings.DEVELOPER_BLOG_URL = url

        update_blog_posts()

        assert BlogPost.objects.count() == 5

        bp = BlogPost.objects.all()[0]
        url = (
            "http://blog.mozilla.com/addons/2011/06/10/"
            "update-in-time-for-thunderbird-5/"
        )
        assert bp.title == 'Test!'
        assert bp.date_posted == datetime.date(2011, 6, 10)
        assert bp.permalink == url
