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
            raise http.Http404()

    # We treat blocked files like public files so users get the update.
    if file.status in [amo.STATUS_PUBLIC, amo.STATUS_BLOCKED]:
        path = webapp.sign_if_packaged(file.version_id)

    else:
        # This is someone asking for an unsigned packaged app.
        if not acl.check_addon_ownership(request, webapp, dev=True):
            raise http.Http404()

        path = file.file_path

    log.info('Downloading package: %s from %s' % (webapp.id, path))
    return HttpResponseSendFile(request, path, content_type='application/zip',
                                etag=file.hash.split(':')[-1])
