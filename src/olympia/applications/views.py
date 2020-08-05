from django.core.cache import cache
from django.db.transaction import non_atomic_requests
from django.utils.translation import ugettext

from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.status import HTTP_201_CREATED, HTTP_202_ACCEPTED

from olympia import amo
from olympia.amo.feeds import BaseFeed
from olympia.amo.templatetags.jinja_helpers import absolutify, url
from olympia.amo.utils import render
from olympia.api.permissions import GroupPermission
from olympia.versions.compare import version_dict, version_re

from .models import AppVersion


def get_versions(order=('application', 'version_int')):
    def fetch_versions():
        apps = amo.APP_USAGE
        versions = {app.id: [] for app in apps}
        qs = list(AppVersion.objects.order_by(*order)
                  .filter(application__in=versions)
                  .values_list('application', 'version'))
        for app, version in qs:
            versions[app].append(version)
        return apps, versions
    return cache.get_or_set('getv' + ':'.join(order), fetch_versions)


@non_atomic_requests
def appversions(request):
    apps, versions = get_versions()
    return render(request, 'applications/appversions.html',
                  {'apps': apps, 'versions': versions})


class AppversionsFeed(BaseFeed):
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


class AppVersionView(APIView):
    permission_classes = [GroupPermission(amo.permissions.APPVERSIONS_CREATE)]

    def put(self, request, *args, **kwargs):
        # For each request, we'll try to create up to 3 versions, one for the
        # parameter in the URL, one for the corresponding "release" version if
        # it's different (if 79.0a1 is passed, the base would be 79.0. If 79.0
        # is passed, then we'd skip that one as they are the same) and a last
        # one for the corresponding max version with a star (if 79.0 or 79.0a1
        # is passed, then this would be 79.*)
        # breakpoint()
        application = amo.APPS.get(kwargs.get('application'))
        if not application:
            raise ParseError('Invalid application parameter')
        requested_version = kwargs.get('version')
        if not requested_version or not version_re.match(requested_version):
            raise ParseError('Invalid version parameter')
        version_data = version_dict(requested_version)
        release_version = '%d.%d' % (
            version_data['major'], version_data['minor1'] or 0)
        star_version = '%d.*' % version_data['major']
        _, created_requested = AppVersion.objects.get_or_create(
            application=application.id, version=requested_version)
        if requested_version != release_version:
            _, created_release = AppVersion.objects.get_or_create(
                application=application.id, version=release_version)
        else:
            created_release = False
        if requested_version != star_version:
            _, created_star = AppVersion.objects.get_or_create(
                application=application.id, version=star_version)
        else:
            created_star = False
        created = created_requested or created_release or created_star
        status_code = HTTP_201_CREATED if created else HTTP_202_ACCEPTED
        return Response(status=status_code)
