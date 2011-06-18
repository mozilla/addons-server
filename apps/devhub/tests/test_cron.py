import datetime
import os

from django.conf import settings

from nose.tools import eq_
import test_utils

from devhub.cron import update_blog_posts
from devhub.models import BlogPost


class TestRSS(test_utils.TestCase):

    def test_rss_cron(self):
        url = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                             'rss_feeds', 'blog.xml')

        settings.DEVELOPER_BLOG_URL = url

        update_blog_posts()

        eq_(BlogPost.objects.count(), 5)

        bp = BlogPost.objects.all()[0]
        url = ("http://blog.mozilla.com/addons/2011/06/10/"
               "update-in-time-for-thunderbird-5/")
        eq_(bp.title, 'Test!')
        eq_(bp.date_posted, datetime.date(2011, 6, 10))
        eq_(bp.permalink, url)

