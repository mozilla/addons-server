from django import http
from django.shortcuts import get_object_or_404

import commonware.log

from access import acl
from addons.models import Addon
import amo
from amo.utils import HttpResponseSendFile
from files.models import File


log = commonware.log.getLogger('z.downloads')


def download_file(request, file_id, type=None):
    file = get_object_or_404(File.objects, pk=file_id)
    webapp = get_object_or_404(Addon.objects, pk=file.version.addon_id)

    if webapp.is_disabled or file.status == amo.STATUS_DISABLED:
        if not acl.check_addon_ownership(request, webapp, viewer=True,
                                         ignore_disabled=True):
            raise http.Http404()

    log.info('Downloading: %s from %s' % (webapp.id, file.file_path))
    return HttpResponseSendFile(request, file.file_path)
