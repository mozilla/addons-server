from urlparse import urlparse

from django import http
# I'm so glad we named a function in here settings...
from django.conf import settings as site_settings
from django.contrib import admin
from django.shortcuts import redirect
from django.views import debug

import commonware.log
from hera.contrib.django_forms import FlushForm
from hera.contrib.django_utils import get_hera, flush_urls
import jinja2
import jingo

from amo import messages
import amo.models
from addons.models import Addon
from files.models import Approval
from versions.models import Version

log = commonware.log.getLogger('z.zadmin')


@admin.site.admin_view
def flagged(request):
    addons = Addon.objects.filter(admin_review=True).order_by('-created')

    if request.method == 'POST':
        ids = map(int, request.POST.getlist('addon_id'))
        Addon.objects.filter(id__in=ids).update(admin_review=False)
        # The sql update doesn't invalidate anything, do it manually.
        invalid = [addon for addon in addons if addon.id in ids]
        Addon.objects.invalidate(*invalid)
        return redirect('zadmin.flagged')

    sql = """SELECT {t}.* FROM {t} JOIN (
                SELECT addon_id, MAX(created) AS created
                FROM {t}
                GROUP BY addon_id) as J
             ON ({t}.addon_id = J.addon_id AND {t}.created = J.created)
             WHERE {t}.addon_id IN {ids}"""
    approvals_sql = sql + """
        AND (({t}.reviewtype = 'nominated' AND {t}.action = %s)
             OR ({t}.reviewtype = 'pending' AND {t}.action = %s))"""

    ids = '(%s)' % ', '.join(str(a.id) for a in addons)
    versions_sql = sql.format(t=Version._meta.db_table, ids=ids)
    approvals_sql = approvals_sql.format(t=Approval._meta.db_table, ids=ids)

    versions = dict((x.addon_id, x) for x in
                    Version.objects.raw(versions_sql))
    approvals = dict((x.addon_id, x) for x in
                     Approval.objects.raw(approvals_sql,
                                          [amo.STATUS_NOMINATED,
                                           amo.STATUS_PENDING]))

    for addon in addons:
        addon.version = versions.get(addon.id)
        addon.approval = approvals.get(addon.id)

    return jingo.render(request, 'zadmin/flagged_addon_list.html',
                        {'addons': addons})


@admin.site.admin_view
def hera(request):
    form = FlushForm(initial={'flushprefix': site_settings.SITE_URL})

    boxes = []
    configured = False  # Default to not showing the form.
    for i in site_settings.HERA:
        hera = get_hera(i)
        r = {'location': urlparse(i['LOCATION'])[1], 'stats': False}
        if hera:
            r['stats'] = hera.getGlobalCacheInfo()
            configured = True
        boxes.append(r)

    if not configured:
        messages.error(request, "Hera is not (or mis-)configured.")
        form = None

    if request.method == 'POST' and hera:
        form = FlushForm(request.POST)
        if form.is_valid():
            expressions = request.POST['flushlist'].splitlines()

            for url in expressions:
                num = flush_urls([url], request.POST['flushprefix'], True)
                msg = ("Flushed %d objects from front end cache for: %s"
                       % (len(num), url))
                log.info("[Hera] (user:%s) %s" % (request.user, msg))
                messages.success(request, msg)

    return jingo.render(request, 'zadmin/hera.html',
                        {'form': form, 'boxes': boxes})


@admin.site.admin_view
def settings(request):
    settings_dict = debug.get_safe_settings()

    # sigh
    settings_dict['HERA'] = []
    for i in site_settings.HERA:
        settings_dict['HERA'].append(debug.cleanse_setting('HERA', i))

    return jingo.render(request, 'zadmin/settings.html',
                        {'settings_dict': settings_dict})


@admin.site.admin_view
def env(request):
    return http.HttpResponse(u'<pre>%s</pre>' % (jinja2.escape(request)))
