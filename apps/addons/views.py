from django import http

import jingo

from stats.models import GlobalStat


# pylint: disable-msg: W0613
def addon_detail(request, addon_id):
    return http.HttpResponse('this is addon %s' % addon_id)


def home(request):
    gs = GlobalStat.objects
    downloads = gs.filter(name='addon_total_downloads').latest()
    pings = gs.filter(name='addon_total_updatepings').latest()

    return jingo.render(request, 'addons/home.html',
                        {'downloads': downloads, 'pings': pings})
