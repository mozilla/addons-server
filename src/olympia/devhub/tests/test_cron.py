import json
import os
from datetime import date, datetime

from django.conf import settings

import responses

from olympia.amo.tests import TestCase
from olympia.devhub.cron import update_blog_posts
from olympia.devhub.models import BlogPost


class TestUpdateBlogPosts(TestCase):
    @classmethod
    def setUpTestData(cls):
        blog_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'json_feeds', 'blog.json'
        )
        with open(blog_path) as blog_file:
            cls.content = json.load(blog_file)

    def setUp(self):
        responses.add(
            responses.GET,
            settings.DEVELOPER_BLOG_URL,
            json=self.content,
        )

    def test_from_empty(self):
        assert BlogPost.objects.count() == 0

        update_blog_posts()

        assert BlogPost.objects.count() == 5
        post = BlogPost.objects.all()[0]
        assert post.post_id == 9022
        assert post.title == 'Thank you, Recommended Extensions Community Board!'
        assert post.date_posted == date(2021, 8, 5)
        assert post.date_modified == datetime(2021, 8, 6, 11, 7, 11)
        assert post.permalink == (
            'https://blog.mozilla.org/addons/2021/08/05/'
            'thank-you-recommended-extensions-community-board/'
        )

    def test_replace_existing(self):
        no_change = BlogPost.objects.create(
            post_id=9018,
            date_posted=date(2021, 7, 29),
            date_modified=datetime(2021, 7, 28, 13, 17, 37),
            title='Foo',
        )
        # change because different modified
        changed = BlogPost.objects.create(
            post_id=9012,
            title='Baa',
        )
        old1 = BlogPost.objects.create(post_id=12345)
        old2 = BlogPost.objects.create(post_id=67890)

        update_blog_posts()

        assert BlogPost.objects.count() == 5
        post = BlogPost.objects.all()[0]
        assert post.title == 'Thank you, Recommended Extensions Community Board!'

        assert not BlogPost.objects.filter(id=old1.id).exists()
        assert not BlogPost.objects.filter(id=old2.id).exists()

        # Post 9018 not updated because it was already there and modified hadn't changed
        assert (
            BlogPost.objects.get(post_id=9018).title
            == no_change.reload().title
            == 'Foo'
        )

        # post 9012 was updated because the modified date was different
        assert (
            BlogPost.objects.get(post_id=9012).title
            == changed.reload().title
            == ('Review Articles on AMO and New Blog Name')
        )
