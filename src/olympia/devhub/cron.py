from datetime import datetime

from django.conf import settings
from django.core.exceptions import BadRequest

import requests

import olympia.core.logger

from olympia.devhub.models import BlogPost


log = olympia.core.logger.getLogger('z.cron')


def update_blog_posts():
    """Update the blog post cache."""
    response = requests.get(settings.DEVELOPER_BLOG_URL, timeout=10)
    try:
        items = response.json()
    except requests.exceptions.JSONDecodeError:
        items = None
    if not (response.status_code == 200 and items and len(items) > 1):
        raise BadRequest('Developer blog JSON import failed.')

    latest_five = items[:5]
    latest_five_ids = [item['id'] for item in latest_five]
    BlogPost.objects.exclude(post_id__in=latest_five_ids).delete()
    existing_blogposts = {post.post_id: post for post in BlogPost.objects.all()}

    for item in latest_five:
        existing = existing_blogposts.get(item['id'])
        data = {
            'title': item['title']['rendered'],
            'date_posted': datetime.strptime(item['date'], '%Y-%m-%dT%H:%M:%S'),
            'date_modified': datetime.strptime(item['modified'], '%Y-%m-%dT%H:%M:%S'),
            'permalink': item['link'],
        }
        if not existing:
            BlogPost.objects.create(post_id=item['id'], **data)
        elif existing.date_modified != data['date_modified']:
            existing.update(**data)

    log.info(f'Adding {len(latest_five)} blog posts.')
