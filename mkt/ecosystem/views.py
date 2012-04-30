from django.shortcuts import get_object_or_404

import commonware.log
import jingo

from .models import MdnCache
from .tasks import refresh_mdn_cache, tutorials, locales


log = commonware.log.getLogger('z.ecosystem')


def landing(request):
    return jingo.render(request, 'ecosystem/landing.html')


def tutorial(request, page=None):

    if not page:
        page = 'apps'

    if request.LANG:
        locale = request.LANG.split('-')[0]
        if not locale in locales:
            locale = 'en'
    else:
        locale = 'en'

    data = get_object_or_404(MdnCache, name=page, locale=locale)

    ctx = {
        'tutorials': tutorials,
        'page': page,
        'content': data.content,
        'toc': data.toc
    }

    return jingo.render(request, 'ecosystem/tutorial.html', ctx)
