from django.contrib import admin
from django.db.models import Q
from django.shortcuts import redirect

import jingo

import amo.models
from addons.models import Addon
from files.models import Approval
from versions.models import Version


@admin.site.admin_view
def flagged(request):
    addons = Addon.objects.filter(admin_review=True).order_by('-created')

    if request.method == 'POST':
        ids = map(int, request.POST.getlist('addon_id'))
        Addon.objects.filter(id__in=ids).update(admin_review=False)
        # The sql update doesn't invalidate anything, do it manually.
        invalid = [addon for addon in addons if addon.id in ids]
        Addon.objects.invalidate(*invalid)
        return redirect('admin.flagged')

    for addon in addons:
        try:
            addon.version = Version.objects.filter(addon=addon).latest()
        except Version.DoesNotExist:
            pass

        try:
            q = (Q(reviewtype='nominated', action=amo.STATUS_NOMINATED) |
                Q(reviewtype='pending', action=amo.STATUS_PENDING))
            addon.approval = Approval.objects.filter(q, addon=addon).latest()
        except Approval.DoesNotExist:
            pass

    return jingo.render(request, 'admin/flagged_addon_list.html',
                        {'addons': addons})
