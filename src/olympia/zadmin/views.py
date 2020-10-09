from django.conf import settings
from django.contrib import admin
from django.contrib.auth import login
from django.contrib.auth.signals import user_logged_in
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404

import olympia.core.logger

from olympia.accounts.views import add_api_token_to_response
from olympia.amo import messages
from olympia.amo.decorators import json_view, post_required
from olympia.amo.utils import render
from olympia.files.models import File
from olympia.users.models import UserProfile


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
    messages.success(request,
                     'File hash and size recalculated for file %d.' % file.id)
    return {'success': 1}


def local_auth_workaround(request):
    """Special view to log in or create users on local envs without relying
    on FxA. Only enabled when settings.DEBUG is True."""
    if not settings.DEBUG:
        raise ImproperlyConfigured(
            'Can not use this view if settings.DEBUG is not True')
    performed_auth = False
    if request.method == 'POST':
        email = request.POST.get('email')
        if email:
            user, created = UserProfile.objects.get_or_create(email=email)
            log.info('Logging in user %s with local auth workaround', user)
            user_logged_in.send(sender=__name__, request=request, user=user)
            login(request, user)
            request.session.save()
            performed_auth = True
    response = render(request, 'zadmin/local_auth_workaround.html')
    if performed_auth:
        add_api_token_to_response(response, user)
    return response
