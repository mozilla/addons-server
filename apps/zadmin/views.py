from django import http
# I'm so glad we named a function in here settings...
from django.conf import settings as site_settings
from django.contrib import admin
from django.contrib import messages
from django.shortcuts import redirect
from django.views import debug

import commonware.log
from hera import Hera
from hera.contrib.django_forms import FlushForm
import jinja2
import jingo

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
    def _hera_fail(e):
        msg = "We had some trouble talking to zeus"
        messages.error(request, "%s: %s" % (msg, e))
        log.error("[Hera] (user:%s): %s" % (request.user, e))

    form = FlushForm(initial={'flushprefix': site_settings.SITE_URL})

    try:
        username = site_settings.HERA['username']
        password = site_settings.HERA['password']
        location = site_settings.HERA['location']
    except (KeyError, AttributeError):
        messages.error(request, "Sorry, Hera is not configured. :(")
        form = None

    if request.method == 'POST':
        form = FlushForm(request.POST)
        if form.is_valid():
            hera = Hera(username, password, location)
            expressions = request.POST['flushlist'].splitlines()

            for i in expressions:
                pattern = "%s%s" % (request.POST['flushprefix'], i)
                total = len(hera.flushObjectsByPattern(pattern,
                                                       return_list=True))

                msg = "Flushing %s objects matching %s from cache" % (total,
                                                                      pattern)
                log.info("[Hera] (user:%s) %s" % (request.user, msg))
                messages.success(request, msg)

    try:
        hera = Hera(username, password, location)
        stats = hera.getGlobalCacheInfo()
    except Exception, e:
        # suds throws generic exceptions...
        stats = None
        form = None
        _hera_fail(e)

    return jingo.render(request, 'zadmin/hera.html',
                        {'form': form, 'stats': stats})


@admin.site.admin_view
def settings(request):
    return jingo.render(request, 'zadmin/settings.html',
                        {'settings_dict': debug.get_safe_settings()})


@admin.site.admin_view
def env(request):
    return http.HttpResponse(u'<pre>%s</pre>' % (jinja2.escape(request)))
