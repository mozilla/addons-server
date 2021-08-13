import datetime
import json
import os

from django.conf import settings

import responses

from olympia.devhub.cron import update_blog_posts
from olympia.devhub.models import BlogPost


def test_update_blog_posts():
    blog_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'json_feeds', 'blog.json'
    )
    with open(blog_path) as blog_file:
        content = json.load(blog_file)

    responses.add(
        responses.GET,
        settings.DEVELOPER_BLOG_URL,
        json=content,
    )

    update_blog_posts()

    assert BlogPost.objects.count() == 5

    post = BlogPost.objects.all()[0]
    assert post.title == 'Thank you, Recommended Extensions Community Board!'
    assert post.date_posted == datetime.date(2021, 8, 5)
    assert post.permalink == (
        'https://blog.mozilla.org/addons/2021/08/05/'
        'thank-you-recommended-extensions-community-board/'
    )
