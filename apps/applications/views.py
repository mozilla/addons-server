import json

from django.contrib.syndication.views import Feed
from django.http import HttpResponse
from django.shortcuts import render

import caching.base as caching
from tower import ugettext as _

import amo
from amo.helpers import url, absolutify
from .models import AppVersion


def get_versions(order=('application', 'version_int')):
    def f():
        apps = amo.APP_USAGE
        versions = dict((app.id, {"name": unicode(app.pretty),
                                  "guid": app.guid,
                                  "versions": []}) for app in apps)
        qs = list(AppVersion.objects.order_by(*order)
                  .filter(application__in=versions)
                  .values_list('application', 'version'))
        for app, version in qs:
            versions[app]["versions"].append(version)
        return versions
    return caching.cached(f, 'getv' + ''.join(order))


def appversions(request):
    apps = get_versions()
    return render(request, 'applications/appversions.html', dict(apps=apps))


def appversions_json(request):
    data = json.dumps(get_versions())
    return HttpResponse(data, mimetype='application/json')


class AppversionsFeed(Feed):
    # appversions aren't getting a created date so the sorting is kind of
    # wanky.  I blame fligtar.

    def title(self):
        return _('Application Versions')

    def link(self):
        return absolutify(url('apps.appversions'))

    def description(self):
        return _('Acceptable versions for all applications on AMO.')

    def items(self):
        versions = get_versions().itervalues()
        return versions

    def item_title(self, item):
        return u'%s %s' % (item['name'], item['versions'][-1])

    item_description = ''

    def item_link(self):
        return self.link()

    def item_guid(self, item):
        return self.item_link() + '%s:%s' % (item['name'],
                                             item['versions'][-1])
