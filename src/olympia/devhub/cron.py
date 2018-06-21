from django.conf import settings

import feedparser

from dateutil import parser

import olympia.core.logger

from olympia.devhub.models import BlogPost


def update_blog_posts():
    """Update the blog post cache."""
    items = feedparser.parse(settings.DEVELOPER_BLOG_URL)['items']
    if not items:
        return

    BlogPost.objects.all().delete()

    for item in items[:5]:
        post = {}
        post['title'] = item.title
        post['date_posted'] = parser.parse(item.published)
        post['permalink'] = item.link
        BlogPost.objects.create(**post)

    log.info('Adding %d blog posts.' % BlogPost.objects.count())
