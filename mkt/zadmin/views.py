import datetime

import jingo

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect

import amo
from access import acl
from addons.models import Category
from amo.decorators import any_permission_required, write
from amo.utils import chunked
from zadmin.decorators import admin_required

import mkt
from mkt.webapps.models import Webapp
from mkt.webapps.tasks import update_manifests
from mkt.zadmin.models import (FeaturedApp, FeaturedAppCarrier,
                               FeaturedAppRegion)



@transaction.commit_on_success
@write
@any_permission_required([('Admin', '%'),
                          ('FeaturedApps', '%')])
def featured_apps_admin(request):
    return jingo.render(request, 'zadmin/featuredapp.html')


@any_permission_required([('Admin', '%'),
                          ('FeaturedApps', '%')])
def featured_apps_ajax(request):
    if request.method == 'GET':
        cat = request.GET.get('category', None) or None
        if cat:
            cat = int(cat)
    elif request.method == 'POST':
        if not acl.action_allowed(request, 'FeaturedApps', 'Edit'):
            raise PermissionDenied
        cat = request.POST.get('category', None) or None
        if cat:
            cat = int(cat)
        deleteid = request.POST.get('delete', None)
        if deleteid:
            FeaturedApp.uncached.filter(category__id=cat,
                                       app__id=int(deleteid)).delete()
        appid = request.POST.get('add', None)
        if appid:
            app, created = FeaturedApp.uncached.get_or_create(category_id=cat,
                                                              app_id=int(appid))
            if created:
                FeaturedAppRegion.objects.create(
                    featured_app=app, region=mkt.regions.WORLDWIDE.id)
    else:
        cat = None
    apps_regions_carriers = []
    for app in FeaturedApp.objects.filter(category__id=cat):
        regions = app.regions.values_list('region', flat=True)
        excluded_regions = app.app.addonexcludedregion.values_list('region',
                                                                   flat=True)
        carriers = app.carriers.values_list('carrier', flat=True)
        apps_regions_carriers.append((app, regions, excluded_regions, carriers))
    return jingo.render(request, 'zadmin/featured_apps_ajax.html',
                        {'apps_regions_carriers': apps_regions_carriers,
                         'regions': mkt.regions.REGIONS_CHOICES,
                         'carriers': settings.CARRIER_URLS})


@any_permission_required([('Admin', '%'),
                          ('FeaturedApps', 'Edit')])
def set_attrs_ajax(request):
    regions = request.POST.getlist('region[]')
    carriers = set(request.POST.getlist('carrier[]'))
    startdate = request.POST.get('startdate', None)
    enddate = request.POST.get('enddate', None)

    app = request.POST.get('app', None)
    if not app:
        return HttpResponse()
    fa = FeaturedApp.uncached.get(pk=app)
    if regions or carriers:
        regions = set(int(r) for r in regions)
        fa.regions.exclude(region__in=regions).delete()
        to_create = regions - set(fa.regions.filter(region__in=regions)
                                  .values_list('region', flat=True))
        excluded_regions = [e.region for e in fa.app.addonexcludedregion.all()]
        for i in to_create:
            if i in excluded_regions:
                continue
            FeaturedAppRegion.objects.create(featured_app=fa, region=i)

        fa.carriers.exclude(carrier__in=carriers).delete()
        to_create = carriers - set(fa.carriers.filter(carrier__in=carriers)
                                   .values_list('carrier', flat=True))
        for c in to_create:
            FeaturedAppCarrier.objects.create(featured_app=fa, carrier=c)

    if startdate:
        fa.start_date = datetime.datetime.strptime(startdate, '%Y-%m-%d')
    else:
        fa.start_date = None
    if enddate:
        fa.end_date = datetime.datetime.strptime(enddate, '%Y-%m-%d')
    else:
        fa.end_date = None
    fa.save()
    return HttpResponse()


@any_permission_required([('Admin', '%'),
                          ('FeaturedApps', '%')])
def featured_categories_ajax(request):
    cats = Category.objects.filter(type=amo.ADDON_WEBAPP)
    return jingo.render(request, 'zadmin/featured_categories_ajax.html', {
        'homecount': FeaturedApp.uncached.filter(category=None).count(),
        'categories': [{
            'name': cat.name,
            'id': cat.pk,
            'count': FeaturedApp.uncached.filter(category=cat).count()
        } for cat in cats]})


@admin_required(reviewers=True)
def manifest_revalidation(request):
    if request.method == 'POST':
        # collect the apps to revalidate
        qs = Q(is_packaged=False, status=amo.STATUS_PUBLIC,
               disabled_by_user=False)
        webapp_pks = Webapp.objects.filter(qs).values_list('pk', flat=True)

        for pks in chunked(webapp_pks, 100):
            update_manifests.delay(list(pks), check_hash=False)

        amo.messages.success(request, "Manifest revalidation queued")

    return jingo.render(request, 'zadmin/manifest.html')
