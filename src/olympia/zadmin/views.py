from django.contrib import admin
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo import messages
from olympia.amo.decorators import (
    json_view, permission_required, post_required)
from olympia.amo.utils import render
from olympia.files.models import File


log = olympia.core.logger.getLogger('z.zadmin')


@permission_required(amo.permissions.ANY_ADMIN)
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return render(request, 'zadmin/index.html', {'log': log})


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
