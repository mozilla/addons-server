from datetime import datetime

from django.conf import settings

import requests

import olympia.core.logger

from olympia.devhub.models import BlogPost


log = olympia.core.logger.getLogger('z.cron')


def update_blog_posts():
    """Update the blog post cache."""
    items = requests.get(settings.DEVELOPER_BLOG_URL, timeout=10).json()
    if not items:
        return

    BlogPost.objects.all().delete()

    for item in items[:5]:
        BlogPost.objects.create(
            title=item['title']['rendered'],
            date_posted=datetime.strptime(item['date'], '%Y-%m-%dT%H:%M:%S'),
            permalink=item['link'],
        )

    log.info(f'Adding {BlogPost.objects.count():d} blog posts.')
