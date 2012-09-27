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

    log.info('Downloading package: %s from %s' % (webapp.id,
                                                  file.file_path))
    path = webapp.sign_if_packaged(file.version_id)
    return HttpResponseSendFile(request, path, content_type='application/zip')
