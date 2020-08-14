from django.contrib import admin
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404, redirect

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo import messages
from olympia.amo.decorators import (
    json_view, permission_required, post_required)
from olympia.amo.utils import HttpResponseXSendFile, render
from olympia.files.models import File, FileUpload

from .decorators import admin_required


log = olympia.core.logger.getLogger('z.zadmin')


@admin.site.admin_view
def fix_disabled_file(request):
    file_ = None
    if request.method == 'POST' and 'file' in request.POST:
        file_ = get_object_or_404(File, id=request.POST['file'])
        if 'confirm' in request.POST:
            file_.unhide_disabled_file()
            messages.success(request, 'We have done a great thing.')
            return redirect('zadmin.fix-disabled')
    return render(request, 'zadmin/fix-disabled.html',
                  {'file': file_, 'file_id': request.POST.get('file', '')})


@permission_required(amo.permissions.ANY_ADMIN)
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return render(request, 'zadmin/index.html', {'log': log})


@admin_required
def download_file_upload(request, uuid):
    upload = get_object_or_404(FileUpload, uuid=uuid)

    return HttpResponseXSendFile(request, upload.path,
                                 content_type='application/octet-stream')


@admin.site.admin_view
@post_required
@json_view
def recalc_hash(request, file_id):

    file = get_object_or_404(File, pk=file_id)
    file.size = storage.size(file.file_path)
    file.hash = file.generate_hash()
    file.save()

    log.info('Recalculated hash for file ID %d' % file.id)
    messages.success(request,
                     'File hash and size recalculated for file %d.' % file.id)
    return {'success': 1}
