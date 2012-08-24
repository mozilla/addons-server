import datetime

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
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


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
            app, created = FeaturedApp.objects.get_or_create(category_id=cat,
                                                             app_id=int(appid))
            if created:
                FeaturedAppRegion.objects.create(featured_app=app,
                    region=mkt.regions.WORLDWIDE.id)
    else:
        cat = None
    apps_regions = []
    for app in FeaturedApp.objects.filter(category__id=cat):
        regions = app.regions.values_list('region', flat=True)
        apps_regions.append((app, regions))
    return jingo.render(request, 'zadmin/featured_apps_ajax.html',
                        {'apps_regions': apps_regions,
                         'regions': mkt.regions.REGIONS_CHOICES})


@admin_required
def set_attrs_ajax(request):
    regions = request.POST.getlist('region[]')
    startdate = request.POST.get('startdate', None)
    enddate = request.POST.get('enddate', None)

    app = request.POST.get('app', None)
    if regions and app:
        fa = FeaturedApp.objects.get(pk=app)
        regions = set(int(r) for r in regions)
        fa.regions.exclude(region__in=regions).delete()
        to_create = regions - set(fa.regions.filter(region__in=regions)
                                  .values_list('region', flat=True))
        for i in to_create:
            FeaturedAppRegion.objects.create(featured_app=fa, region=i)

    if startdate and app:
        FeaturedApp.objects.update(
            start_date=datetime.datetime.strptime(startdate,
                                                 '%Y-%m-%d'))
    if enddate and app:
        FeaturedApp.objects.update(
            end_date=datetime.datetime.strptime(enddate,
                                               '%Y-%m-%d'))
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
