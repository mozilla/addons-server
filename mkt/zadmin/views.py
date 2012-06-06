import jingo

from django.contrib import admin
from django.shortcuts import redirect
from django.db import transaction

import amo
from amo import messages
from amo.decorators import write, json_view
from amo.urlresolvers import reverse
from addons.models import Category, AddonCategory
from bandwagon.models import CollectionAddon

from mkt.ecosystem.tasks import refresh_mdn_cache, tutorials
from mkt.ecosystem.models import MdnCache
from mkt.webapps.models import Webapp
from mkt.zadmin.models import FeaturedApp


@transaction.commit_on_success
@write
@admin.site.admin_view
def featured_apps_admin(request):
    return jingo.render(request, 'zadmin/featuredapp.html')


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


@admin.site.admin_view
def featured_apps_ajax(request):
    if request.GET:
        cat = request.GET.get('category', None) or None
        if cat:
            cat = int(cat)
    elif request.POST:
        cat = request.POST.get('category', None) or None
        if cat:
            cat = int(cat)
        deleteid = request.POST.get('delete', None)
        if deleteid:
            FeaturedApp.objects.filter(category__id=cat,
                                       app__id=int(deleteid)).delete()
        appid = request.POST.get('add', None)
        if appid:
            FeaturedApp.objects.get_or_create(category_id=cat,
                                              app_id=int(appid))
    else:
        cat = None

    apps = FeaturedApp.objects.filter(category__id=cat)
    return jingo.render(request, 'zadmin/featured_apps_ajax.html',
                        {'apps': apps})

@admin.site.admin_view
def featured_categories_ajax(request):
    cats = Category.objects.filter(type=amo.ADDON_WEBAPP)
    return jingo.render(request, 'zadmin/featured_categories_ajax.html', {
            'homecount': FeaturedApp.objects.filter(
                category=None).count(),
            'categories': [{
                    'name': cat.name,
                    'id': cat.pk,
                    'count': FeaturedApp.objects.filter(category=cat).count()
                    } for cat in cats]})
