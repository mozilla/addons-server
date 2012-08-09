import jingo

from django.contrib import admin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.db import transaction

import amo
from amo.decorators import write
from addons.models import Category
from zadmin.decorators import admin_required

import mkt
from mkt.ecosystem.tasks import refresh_mdn_cache, tutorials
from mkt.ecosystem.models import MdnCache
from mkt.zadmin.models import FeaturedApp


@transaction.commit_on_success
@write
@admin_required
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


@admin_required
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
                        {'apps': apps,
                         'regions': mkt.regions.REGIONS_CHOICES})


@admin_required
def set_region_ajax(request):
    region = request.POST.get('region', None)
    app = request.POST.get('app', None)
    if region and app:
        FeaturedApp.objects.filter(pk=app).update(region=region)
    return HttpResponse()


@admin_required
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
