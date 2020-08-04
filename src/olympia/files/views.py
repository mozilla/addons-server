from django.core.exceptions import PermissionDenied
from django import http, shortcuts
from django.utils.crypto import constant_time_compare

import olympia.core.logger

from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import HttpResponseXSendFile

from .models import FileUpload


log = olympia.core.logger.getLogger('z.addons')


@use_primary_db
def serve_file_upload(request, uuid):
    """
    This is to serve file uploads using authenticated download URLs. This is
    currently used by the "scanner" services.
    """
    upload = shortcuts.get_object_or_404(FileUpload, uuid=uuid)
    access_token = request.GET.get('access_token')

    if not access_token:
        log.error('Denying access to %s, no token.', upload.id)
        raise PermissionDenied

    if not constant_time_compare(access_token, upload.access_token):
        log.error('Denying access to %s, token invalid.', upload.id)
        raise PermissionDenied

    if not upload.path:
        log.info('Preventing access to %s, upload path is falsey.' % upload.id)
        return http.HttpResponseGone('upload path does not exist anymore')

    return HttpResponseXSendFile(request,
                                 upload.path,
                                 content_type='application/octet-stream')
