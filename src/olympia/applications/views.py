from django.db.transaction import non_atomic_requests
from django.utils.translation import ugettext

import caching.base as caching

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import url, absolutify
from olympia.amo.feeds import NonAtomicFeed
from olympia.amo.utils import render

from .models import AppVersion


def get_versions(order=('application', 'version_int')):
    def f():
        apps = amo.APP_USAGE
        versions = dict((app.id, []) for app in apps)
        qs = list(AppVersion.objects.order_by(*order)
                  .filter(application__in=versions)
                  .values_list('application', 'version'))
        for app, version in qs:
            versions[app].append(version)
        return apps, versions
    return caching.cached(f, 'getv' + ''.join(order))


@non_atomic_requests
def appversions(request):
    apps, versions = get_versions()
    return render(request, 'applications/appversions.html',
                  dict(apps=apps, versions=versions))


class AppversionsFeed(NonAtomicFeed):
    # appversions aren't getting a created date so the sorting is kind of
    # wanky.  I blame fligtar.

    def title(self):
        return ugettext(u'Application Versions')

    def link(self):
        return absolutify(url('apps.appversions'))

    def description(self):
        return ugettext(u'Acceptable versions for all applications on AMO.')

    def items(self):
        apps, versions = get_versions(order=('application', '-version_int'))
        return [(app, version) for app in apps
                for version in versions[app.id][:3]]
        return [(app, versions[app.id][:3]) for app in apps]

    def item_title(self, item):
        app, version = item
        return u'%s %s' % (app.pretty, version)

    item_description = ''

    def item_link(self):
        return self.link()

    def item_guid(self, item):
        return self.item_link() + '%s:%s' % item
