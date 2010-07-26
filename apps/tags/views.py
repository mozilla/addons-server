from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404
import jingo

from tags.models import Tag


def top_cloud(request, num_tags=100):
    """Display 100 (or so) most used tags"""
    """TODO (skeen) Need to take request.APP.id into account, first
       attempts to do so resulted in extreme SQL carnage
       bug 556135 is open to fix"""
    top_tags = Tag.objects.not_blacklisted().select_related(
        'tagstat').order_by('-tagstat__num_addons')[:num_tags]
    return jingo.render(request, 'tags/top_cloud.html',
                        {'top_tags': top_tags})

