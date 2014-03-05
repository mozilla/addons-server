from django.db.models import Q
from django.shortcuts import render

import amo
from amo.utils import chunked
from zadmin.decorators import admin_required

from mkt.webapps.models import Webapp
from mkt.webapps.tasks import update_manifests


@admin_required(reviewers=True)
def manifest_revalidation(request):
    if request.method == 'POST':
        # Collect the apps to revalidate.
        qs = Q(is_packaged=False, status=amo.STATUS_PUBLIC,
               disabled_by_user=False)
        webapp_pks = Webapp.objects.filter(qs).values_list('pk', flat=True)

        for pks in chunked(webapp_pks, 100):
            update_manifests.delay(list(pks), check_hash=False)

        amo.messages.success(request, 'Manifest revalidation queued')

    return render(request, 'zadmin/manifest.html')
