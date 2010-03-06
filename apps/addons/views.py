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

    def __init__(self, request, base, key, default):
        self.opts_dict = dict(self.opts)
        self.request = request
        self.base_queryset = base
        self.field, self.title = self.options(self.request, key, default)
        self.qs = self.filter(self.field)

    def options(self, request, key, default):
        """Get the (option, title) pair we should according to the request."""
        if key in request.GET and request.GET[key] in self.opts_dict:
            opt = request.GET[key]
        else:
            opt = default
        return opt, self.opts_dict[opt]

    def all(self):
        """Get a full mapping of {option: queryset}."""
        return dict((field, self.filter(field)) for field in dict(self.opts))

    def filter(self, field):
        """Get the queryset for the given field."""
        return self.base_queryset & self._filter(field).distinct()

    def _filter(self, field):
        qs = Addon.objects
        if field == 'popular':
            return qs.order_by('-bayesian_rating')
        elif field == 'new':
            return qs.order_by('-created')
        elif field == 'updated':
            return qs.order_by('-last_updated')
        else:
            # It's ok to cache this for a while...it'll expire eventually.
            return qs.featured(self.request.APP).order_by('?')


def home(request):
    try:
        gs = GlobalStat.objects
        downloads = gs.filter(name='addon_total_downloads').latest()
        pings = gs.filter(name='addon_total_updatepings').latest()
    except GlobalStat.DoesNotExist:
        downloads = pings = None

    q = Collection.objects.filter(listed=True, application=request.APP.id)
    collections = q.order_by('-weekly_subscribers')[:3]

    base = Addon.objects.listed(request.APP).exclude(type=amo.ADDON_PERSONA)
    filter = HomepageFilter(request, base, key='browse', default='featured')
    addon_sets = dict((key, qs[:4]) for key, qs in filter.all().items())

    return jingo.render(request, 'addons/home.html',
                        {'downloads': downloads, 'pings': pings,
                         'filter': filter, 'addon_sets': addon_sets,
                         'collections': collections,
                        })
