import json

from django import http
from django.db.transaction import non_atomic_requests
from django.forms.models import modelformset_factory
from django.shortcuts import get_object_or_404, redirect

import olympia.core.logger

from olympia import amo
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon
from olympia.addons.utils import get_featured_ids
from olympia.amo.models import manual_order
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import render
from olympia.browse.views import personas_listing
from olympia.legacy_api import views as legacy_api_views
from olympia.ratings.models import Rating
from olympia.stats.models import GlobalStat
from olympia.versions.compare import version_int
from olympia.zadmin.decorators import admin_required

from .forms import DiscoveryModuleForm
from .models import DiscoveryModule
from .modules import PromoVideoCollection, registry as module_registry


addon_view = addon_view_factory(Addon.objects.valid)

log = olympia.core.logger.getLogger('z.disco')


def get_compat_mode(version):
    # Returns appropriate compat mode based on app version.
    # Replace when we are ready to deal with bug 711698.
    vint = version_int(version)
    return 'ignore' if vint >= version_int('10.0') else 'strict'


@non_atomic_requests
def pane(request, version, platform, compat_mode=None):

    if not compat_mode:
        compat_mode = get_compat_mode(version)

    def from_api(list_type):
        return api_view(request, platform, version, list_type,
                        compat_mode=compat_mode)

    promovideo = PromoVideoCollection().get_items()

    return render(request, 'legacy_discovery/pane.html',
                  {'up_and_coming': from_api('hotness'),
                   'featured_addons': from_api('featured'),
                   'featured_personas': get_featured_personas(request),
                   'version': version, 'platform': platform,
                   'promovideo': promovideo, 'compat_mode': compat_mode})


@non_atomic_requests
def pane_account(request):
    try:
        qs = GlobalStat.objects.filter(name='addon_total_downloads')
        addon_downloads = qs.latest().count
    except GlobalStat.DoesNotExist:
        addon_downloads = None

    return render(request, 'legacy_discovery/pane_account.html',
                  {'addon_downloads': addon_downloads})


@non_atomic_requests
def promos(request, context, version, platform, compat_mode='strict'):
    if platform:
        platform = platform.lower()
    platform = amo.PLATFORM_DICT.get(platform, amo.PLATFORM_ALL)
    modules = get_modules(request, platform.api_name, version)
    return render(request, 'addons/impala/homepage_promos.html',
                  {'modules': modules, 'module_context': context})


@non_atomic_requests
def pane_promos(request, version, platform, compat_mode=None):
    if not compat_mode:
        compat_mode = get_compat_mode(version)

    return promos(request, 'discovery', version, platform, compat_mode)


@non_atomic_requests
def pane_more_addons(request, section, version, platform, compat_mode=None):
    if not compat_mode:
        compat_mode = get_compat_mode(version)

    def from_api(list_type):
        return api_view(request, platform, version, list_type,
                        compat_mode=compat_mode)

    ctx = {}
    if section == 'featured':
        ctx = {'featured_addons': from_api('featured')}
    elif section == 'up-and-coming':
        ctx = {'up_and_coming': from_api('hotness')}

    content = render(request, 'legacy_discovery/more_addons.html', ctx)
    return content


def get_modules(request, platform, version):
    lang = request.LANG
    qs = DiscoveryModule.objects.filter(app=request.APP.id)
    # Remove any modules without a registered backend or an ordering.
    modules = [m for m in qs
               if m.module in module_registry and m.ordering is not None]
    # Remove modules that specify a locales string we're not part of.
    modules = [m for m in modules
               if not m.locales or lang in m.locales.split()]
    modules = sorted(modules, key=lambda x: x.ordering)
    return [module_registry[m.module](request, platform, version)
            for m in modules]


def get_featured_personas(request, category=None, num_personas=6):
    categories, filter, base, category = personas_listing(request, category)
    ids = get_featured_ids(request.APP, request.LANG, type=amo.ADDON_PERSONA)

    return manual_order(base, ids, 'addons.id')[:num_personas]


@non_atomic_requests
def api_view(request, platform, version, list_type, api_version=1.5,
             format='json', content_type='application/json',
             compat_mode='strict'):
    """Wrapper for calling an API view."""
    view = legacy_api_views.ListView()
    view.request, view.version = request, api_version
    view.format, view.content_type = format, content_type
    r = view.process_request(list_type, platform=platform, version=version,
                             compat_mode=compat_mode)
    return json.loads(r.content)


@admin_required
@non_atomic_requests
def module_admin(request):
    APP = request.APP
    # Custom sorting to drop ordering=NULL objects to the bottom.
    qs = DiscoveryModule.objects.raw("""
        SELECT * from discovery_modules WHERE app_id = %s
        ORDER BY ordering IS NULL, ordering""", [APP.id])
    qs.ordered = True  # The formset looks for this.
    _sync_db_and_registry(qs, APP.id)

    Form = modelformset_factory(DiscoveryModule, form=DiscoveryModuleForm,
                                can_delete=True, extra=0)
    formset = Form(request.POST or None, queryset=qs)

    if request.method == 'POST' and formset.is_valid():
        formset.save()
        return redirect('discovery.module_admin')

    return render(
        request, 'legacy_discovery/module_admin.html', {'formset': formset})


def _sync_db_and_registry(qs, app_id):
    """Match up the module registry and DiscoveryModule rows in the db."""
    existing = dict((m.module, m) for m in qs)
    to_add = [m for m in module_registry if m not in existing]
    to_delete = [m for m in existing if m not in module_registry]
    for m in to_add:
        DiscoveryModule.objects.get_or_create(module=m, app=app_id)
    DiscoveryModule.objects.filter(module__in=to_delete, app=app_id).delete()
    if to_add or to_delete:
        qs._result_cache = None


@addon_view
@non_atomic_requests
def addon_detail(request, addon):
    reviews = Rating.without_replies.all().filter(addon=addon, is_latest=True)
    src = request.GET.get('src', 'discovery-details')
    return render(request, 'legacy_discovery/addons/detail.html',
                  {'addon': addon, 'reviews': reviews,
                   'get_replies': Rating.get_replies, 'src': src})


@addon_view
@non_atomic_requests
def addon_eula(request, addon, file_id):
    if not addon.eula:
        return http.HttpResponseRedirect(reverse('discovery.addons.detail',
                                         args=[addon.slug]))
    if file_id is not None:
        version = get_object_or_404(addon.versions, files__id=file_id)
    else:
        version = addon.current_version
    src = request.GET.get('src', 'discovery-details')
    return render(request, 'legacy_discovery/addons/eula.html',
                  {'addon': addon, 'version': version, 'src': src})
