from django import http
from django.shortcuts import get_object_or_404

import commonware.log

import amo
from access import acl
from amo.utils import HttpResponseSendFile
from files.models import File
from mkt.webapps.models import Webapp

log = commonware.log.getLogger('z.downloads')


def download_file(request, file_id, type=None):
    file = get_object_or_404(File, pk=file_id)
    webapp = get_object_or_404(Webapp, pk=file.version.addon_id,
                               is_packaged=True)

    if webapp.is_disabled or file.status == amo.STATUS_DISABLED:
        if not acl.check_addon_ownership(request, webapp, viewer=True,
                                         ignore_disabled=True):
            log.info('Download of %s denied: disabled.' % (webapp.id))
            raise http.Http404()

    # We treat blocked files like public files so users get the update.
    if file.status in [amo.STATUS_PUBLIC, amo.STATUS_BLOCKED]:
        path = webapp.sign_if_packaged(file.version_id)

    else:
        # This is someone asking for an unsigned packaged app.
        if not acl.check_addon_ownership(request, webapp, dev=True):
            log.info('Download of %s denied: not signed yet.' % (webapp.id))
            raise http.Http404()

        path = file.file_path

    # If it's a paid app and its not been paid for stop it downloading unless..
    if webapp.is_premium():
        if not request.user.is_authenticated():
            log.info('Download of %s denied: not logged in.' % (webapp.id))
            return http.HttpResponseForbidden()

        if not webapp.has_purchased(request.amo_user):
            # User hasn't purchased, are they a developer of the app,
            # or a reviewer?
            log.info('Download of %s: not purchased by user.' % (webapp.id))
            if (not request.check_ownership(webapp, require_owner=False,
                                            ignore_disabled=True, admin=False)
                and not acl.check_reviewer(request, only='app')):
                log.info('Download of %s denied: not developer or reviewer.' %
                         (webapp.id))
                return http.HttpResponse(status=402)

    log.info('Downloading package: %s from %s' % (webapp.id, path))
    return HttpResponseSendFile(request, path, content_type='application/zip',
                                etag=file.hash.split(':')[-1])
