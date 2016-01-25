from django.db.transaction import non_atomic_requests
from django.shortcuts import render

from tags.models import Tag


@non_atomic_requests
def top_cloud(request, num_tags=100):
    """Display 100 (or so) most used tags"""
    """TODO (skeen) Need to take request.APP.id into account, first
       attempts to do so resulted in extreme SQL carnage
       bug 556135 is open to fix"""
    top_tags = Tag.objects.not_blacklisted().order_by('-num_addons')[:num_tags]
    return render(request, 'tags/top_cloud.html', {'top_tags': top_tags})
