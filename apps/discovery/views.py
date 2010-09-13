import json
import uuid

from django import http
from django.contrib import admin
from django.forms.models import modelformset_factory
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

import jingo

import amo.utils
import api.utils
import api.views
from addons.models import Addon
from bandwagon.models import Collection, SyncedCollection, CollectionToken
from stats.models import GlobalStat

from .models import DiscoveryModule
from .forms import DiscoveryModuleForm
from .modules import registry as module_registry

def pane(request, version, platform):

    def from_api(list_type):
        r = api_view(request, platform, version, list_type)
        return json.loads(r.content)
    try:
        qs = GlobalStat.objects.filter(name='addon_total_downloads')
        addon_downloads = qs.latest().count
    except GlobalStat.DoesNotExist:
        addon_downloads = None

    return jingo.render(request, 'discovery/pane.html',
                        {'modules': get_modules(request, platform, version),
                         'addon_downloads': addon_downloads,
                         'top_addons': from_api('by_adu'),
                         'featured': from_api('featured')})


def get_modules(request, platform, version):
    lang = request.LANG
    qs = DiscoveryModule.objects.filter(app=request.APP.id)
    # Remove any modules without a registered backend or an ordering.
    modules = [m for m in qs if m.module in module_registry
                                and m.ordering is not None]
    # Remove modules that specify a locales string we're not part of.
    modules = [m for m in modules if not m.locales
                                     or lang in m.locales.split()]
    modules = sorted(modules, key=lambda x: x.ordering)
    return [module_registry[m.module](request, platform, version)
            for m in modules]


def api_view(request, platform, version, list_type,
             api_version=1.5, format='json', mimetype='application/json'):
    """Wrapper for calling an API view."""
    view = api.views.ListView()
    view.request, view.version = request, api_version
    view.format, view.mimetype = format, mimetype
    return view.process_request(list_type, platform=platform,
                                version=version)


@admin.site.admin_view
def module_admin(request):
    APP = request.APP
    # Custom sorting to drop ordering=NULL objects to the bottom.
    qs = DiscoveryModule.uncached.raw("""
        SELECT * from discovery_modules WHERE app_id = %s
        ORDER BY ordering IS NULL, ordering""", [APP.id])
    qs.ordered = True  # The formset looks for this.
    _sync_db_and_registry(qs, APP)

    Form = modelformset_factory(DiscoveryModule, form=DiscoveryModuleForm,
                                can_delete=True, extra=0)
    formset = Form(request.POST or None, queryset=qs)

    if request.method == 'POST' and formset.is_valid():
        formset.save()
        return redirect('discovery.module_admin')

    return jingo.render(request, 'discovery/module_admin.html',
                        {'formset': formset})


def _sync_db_and_registry(qs, app):
    """Match up the module registry and DiscoveryModule rows in the db."""
    existing = dict((m.module, m) for m in qs)
    add = [m for m in module_registry if m not in existing]
    delete = [m for m in existing if m not in module_registry]
    for m in add:
        DiscoveryModule.objects.create(module=m, app_id=app.id)
    for m in delete:
        DiscoveryModule.objects.get(module=m, app=app.id).delete()
    if add or delete:
        qs._result_cache = None


@csrf_exempt
def recommendations(request, limit=5):
    """
    Figure out recommended add-ons for an anonymous user based on POSTed guids.

    POST body looks like {"guids": [...]} with an optional "token" key if
    they've been here before.
    """
    if request.method != 'POST':
        return http.HttpResponseNotAllowed(['POST'])

    try:
        POST = json.loads(request.raw_post_data)
        guids = POST['guids']
    except (ValueError, TypeError, KeyError):
        # Errors: invalid json, didn't get a dict, didn't find "guids".
        return http.HttpResponseBadRequest()

    addon_ids = get_addon_ids(guids)
    token = POST['token'] if 'token' in POST else get_random_token()

    if 'token' in POST:
        q = SyncedCollection.objects.filter(token_set__token=token)
        if q:
            # We've seen this user before.
            synced = q[0]
            if synced.addon_index == Collection.make_index(addon_ids):
                # Their add-ons didn't change, get out quick.
                recs = synced.get_recommendations()
                return _recommendations(request, limit, token, recs)
            else:
                # Remove the link to the current sync, make a new one below.
                synced.token_set.get(token=token).delete()

    synced = get_synced_collection(addon_ids, token)
    recs = synced.get_recommendations()
    return _recommendations(request, limit, token, recs)


def _recommendations(request, limit, token, recs):
    """Return a JSON response for the recs view."""
    ids = list(recs.addons.order_by('collectionaddon__ordering')
               .values_list('id', flat=True))[:limit]
    data = {'token': token, 'recommendations': recs.get_url_path(),
            'addons': [api.utils.addon_to_dict(Addon.objects.get(pk=pk))
                       for pk in ids]}
    content = json.dumps(data, cls=amo.utils.JSONEncoder)
    return http.HttpResponse(content, content_type='application/json')


def get_addon_ids(guids):
    return Addon.objects.filter(guid__in=guids).values_list('id', flat=True)


def get_synced_collection(addon_ids, token):
    """
    Get a synced collection for these addons. May reuse an existing collection.

    The token is associated with the collection.
    """
    index = Collection.make_index(addon_ids)
    try:
        c = (SyncedCollection.objects.no_cache()
             .filter(addon_index=index))[0]
    except IndexError:
        c = SyncedCollection.objects.create(listed=False)
        c.set_addons(addon_ids)

    c.token_set.create(token=token)
    return c


def get_random_token():
    """Get a random token for the user, make sure it's unique."""
    while 1:
        token = unicode(uuid.uuid4())
        if CollectionToken.objects.filter(token=token).count() == 0:
            return token
