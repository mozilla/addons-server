import random

from django import http

import jingo
from l10n import ugettext as _

import amo
from addons.models import Addon
from bandwagon.models import Collection
from stats.models import GlobalStat


# pylint: disable-msg: W0613
def addon_detail(request, addon_id):
    return http.HttpResponse('this is addon %s' % addon_id)


class HomepageFilter(object):
    """
    key: the GET param we look at
    default: the default key we should use
    """

    opts = (('featured', _('Featured')),
            ('popular', _('Popular')),
            ('new', _('Just Added')),
            ('updated', _('Updated')))

    def __init__(self, request, queryset, key, default):
        self.request = request
        self.queryset = queryset
        self.field, self.title = self.options(self.request, key, default)
        self.qs = self.filter(self.field)

    def options(self, request, key, default):
        opts_dict = dict(self.opts)
        if key in request.GET and request.GET[key] in opts_dict:
            opt = request.GET[key]
        else:
            opt = default
        return opt, opts_dict[opt]

    def all(self):
        return dict((field, self.filter(field)) for field in dict(self.opts))

    def filter(self, field):
        qs = (self.queryset.listed(self.request.APP)
              .exclude(type=amo.ADDON_PERSONA))
        if field == 'popular':
            return qs.order_by('-bayesian_rating')
        elif field == 'new':
            return qs.order_by('-created')
        elif field == 'updated':
            return qs.order_by('-last_updated')
        else:
            # It's ok to cache this for a while...it'll expire eventually.
            return (self.queryset.featured(self.request.APP)
                    .exclude(type=amo.ADDON_PERSONA).order_by('?'))


def home(request):
    gs = GlobalStat.objects
    downloads = gs.filter(name='addon_total_downloads').latest()
    pings = gs.filter(name='addon_total_updatepings').latest()

    q = Collection.objects.filter(listed=True, application=request.APP.id)
    collections = q.order_by('-weekly_subscribers')[:3]

    filter = HomepageFilter(request, Addon.objects,
                            key='browse', default='featured')
    addon_sets = dict((key, qs[:4]) for key, qs in filter.all().items())

    return jingo.render(request, 'addons/home.html',
                        {'downloads': downloads, 'pings': pings,
                         'filter': filter, 'addon_sets': addon_sets,
                         'collections': collections,
                        })
