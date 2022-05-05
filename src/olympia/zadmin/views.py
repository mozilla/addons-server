from django.contrib import admin
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404

import olympia.core.logger

from olympia.amo import messages
from olympia.amo.decorators import json_view, post_required
from olympia.files.models import File


log = olympia.core.logger.getLogger('z.zadmin')


@admin.site.admin_view
@post_required
@json_view
def recalc_hash(request, file_id):

    file = get_object_or_404(File, pk=file_id)
    file.size = storage.size(file.file_path)
    file.hash = file.generate_hash()
    file.save()

    log.info('Recalculated hash for file ID %d' % file.id)
    messages.success(request, 'File hash and size recalculated for file %d.' % file.id)
    return {'success': 1}
