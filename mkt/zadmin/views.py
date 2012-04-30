import jingo

from django.contrib import admin
from django.shortcuts import redirect
from django.db import transaction

from amo import messages
from amo.decorators import write
from amo.urlresolvers import reverse
from bandwagon.models import CollectionAddon

from mkt.ecosystem.tasks import refresh_mdn_cache, tutorials
from mkt.ecosystem.models import MdnCache
from mkt.webapps.models import Webapp


@transaction.commit_on_success
@write
@admin.site.admin_view
def featured_apps_admin(request):
    home_collection = Webapp.featured_collection('home')
    category_collection = Webapp.featured_collection('category')

    if request.POST:
        if 'home_submit' in request.POST:
            coll = home_collection
            rowid = 'home'
        elif 'category_submit' in request.POST:
            coll = category_collection
            rowid = 'category'
        existing = set(coll.addons.values_list('id', flat=True))
        requested = set(int(request.POST[k])
                        for k in sorted(request.POST.keys())
                        if k.endswith(rowid + '-webapp'))
        CollectionAddon.objects.filter(collection=coll,
            addon__in=(existing - requested)).delete()
        for id in requested - existing:
            CollectionAddon.objects.create(collection=coll, addon_id=id)
        messages.success(request, 'Changes successfully saved.')
        return redirect(reverse('admin.featured_apps'))

    return jingo.render(request, 'zadmin/featuredapp.html', {
        'home_featured': enumerate(home_collection.addons.all()),
        'category_featured': enumerate(category_collection.addons.all())
    })


@admin.site.admin_view
def ecosystem(request):
    if request.method == 'POST':
        refresh_mdn_cache()
        return redirect(request.path)

    pages = MdnCache.objects.all()
    ctx = {
        'pages': pages,
        'tutorials': tutorials
    }

    return jingo.render(request, 'zadmin/ecosystem.html', ctx)
