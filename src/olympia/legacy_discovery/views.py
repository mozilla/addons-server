from django.db.transaction import non_atomic_requests
from django.forms.models import modelformset_factory
from django.shortcuts import redirect

from olympia import amo
from olympia.amo.utils import render
from olympia.zadmin.decorators import admin_required

from .forms import DiscoveryModuleForm
from .models import DiscoveryModule
from .modules import registry as module_registry


@non_atomic_requests
def promos(request, context, version, platform, compat_mode='strict'):
    if platform:
        platform = platform.lower()
    platform = amo.PLATFORM_DICT.get(platform, amo.PLATFORM_ALL)
    modules = get_modules(request, platform.api_name, version)
    return render(request, 'addons/impala/homepage_promos.html',
                  {'modules': modules})


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
    existing = {m.module: m for m in qs}
    to_add = [m for m in module_registry if m not in existing]
    to_delete = [m for m in existing if m not in module_registry]
    for m in to_add:
        DiscoveryModule.objects.get_or_create(module=m, app=app_id)
    DiscoveryModule.objects.filter(module__in=to_delete, app=app_id).delete()
    if to_add or to_delete:
        qs._result_cache = None
