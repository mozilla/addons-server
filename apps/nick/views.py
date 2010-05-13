"""
This set of views generates download and ADU statistics for featured,
category-featured, and other popular add-ons.  It's useful when you're
analyzing the effectiveness of the featured list, and when picking new add-ons
to feature.
"""
import collections
from datetime import date, timedelta as td
import time

from django import forms
from django.contrib import admin
from django.db.models import Sum, Avg

import jingo
from caching.base import cached_with

import amo
from amo.urlresolvers import reverse
from addons.models import Addon, Category
from stats.models import DownloadCount, UpdateCount


# Helper functions, data structures, and forms.

def CategoryForm(request):
    """Makes a form to select a category for the current app, and a date."""
    q = Category.objects.filter(application=request.APP.id,
                                type=amo.ADDON_EXTENSION)
    choices = (('', '--------'),) + tuple((c.slug, c.name) for c in q)

    class _CategoryForm(forms.Form):
        category = forms.ChoiceField(choices=choices, required=False)
        date = forms.DateField(initial=date.today, required=False)

    return _CategoryForm(request.GET or None)


class StatDelta(object):
    """Compares two values and generates a delta."""

    def __init__(self, current, previous):
        self.current = current
        self.previous = previous
        if previous != 0:
            self.delta = delta = float(current - previous) / previous
        else:
            self.delta = delta = 0
        # This might be useful as a css class.
        if delta > 0:
            self.change = 'positive'
        elif delta < 0:
            self.change = 'negative'
        else:
            self.change = 'neutral'


def gather_stats(qs, key_name, aggregate, date_):
    """Take a ValuesQuerySet and turn it into a dict of StatDeltas."""
    # Take the queryset and compare the aggregate
    # value between last week and 2 weeks ago.

    # Some dates we'll be using: today - 1 week, today - 2 weeks.
    date_1w, date_2w = date_ - td(days=7), date_ - td(days=14)

    rv, tmp = {}, {}
    tmp['cur'] = qs.filter(date__lte=date_, date__gte=date_1w)
    tmp['prev'] = qs.filter(date__lte=date_1w, date__gte=date_2w)
    for name, query in tmp.items():
        tmp[name] = dict((x[key_name], x[aggregate]) for x in query)
    for key, cur_value in tmp['cur'].items():
        rv[key] = StatDelta(cur_value, tmp['prev'].get(key, 0))
    return rv


def attach_stats(request, addons, date_):
    """
    Attach download and adu stats to each addon for the 2 weeks before date_.
    """
    ids = [addon.id for addon in addons]

    date_1w, date_2w = date_ - td(days=7), date_ - td(days=14)

    # Gather download stats.
    q = (DownloadCount.stats.filter(addon__in=ids).values('addon')
         .annotate(Sum('count')))
    downloads = gather_stats(q, 'addon', 'count__sum', date_)

    # Gather active daily user stats.
    q = (UpdateCount.stats.filter(addon__in=ids).values('addon')
         .annotate(Avg('count')))
    adus = gather_stats(q, 'addon', 'count__avg', date_)

    # Download data for sparklines.
    q = (DownloadCount.stats.filter(addon__in=ids, date__gte=date_2w)
         .order_by('addon', 'date').values_list('addon', 'count'))
    sparks = collections.defaultdict(list)
    for addon_id, count in q:
        sparks[addon_id].append(count)

    featured_ids = [a.id for a in Addon.objects.featured(request.APP)]

    # Attach all the extra data to the addon.
    for addon in addons:
        addon.downloads = downloads.get(addon.id, StatDelta(0, 0))
        addon.adus = adus.get(addon.id, StatDelta(0, 0))
        addon.sparks = sparks[addon.id]
        addon.featured = addon.id in featured_ids
        try:
            addon.first_category = addon.categories.all()[0]
        except IndexError:
            pass

    return list(addons)


def get_sections():
    """Get (name, url, title) for each function we expose."""
    return [(func.__name__, reverse(func), title)
            for func, title in _sections]


@admin.site.admin_view
def view(request, func):
    """
    This isn't called directly by anything in urls.py.  Since all the views in
    this module are quite similar, each function marked by @section just
    returns the queryset we should operate on.  The rest of the structure is
    the same.
    """
    qs = func(request).exclude(type=amo.ADDON_PERSONA).distinct()
    date_ = date.today()
    form = CategoryForm(request)

    if form.is_valid():
        date_ = form.cleaned_data['date'] or date_
        category = form.cleaned_data['category']
        if category:
            qs = qs.filter(categories__slug=category)

    addons = amo.utils.paginate(request, qs, per_page=75)
    q = addons.object_list
    cache_key = '%s%s' % (q.query, date_)
    f = lambda: attach_stats(request, q, date_)
    addons.object_list = cached_with(q, f, cache_key)

    c = {'addons': addons, 'section': func.__name__,
         'query': q, 'form': form, 'sections': get_sections()}
    return jingo.render(request, 'nick/featured.html', c)


# This will hold (function, title) pairs that are exposed by @section.
_sections = []


def section(title):
    """
    Add the title and function to _sections and return a wrapper that calls
    ``view`` with the decorated function.
    """
    def decorator(func):
        v = lambda request: view(request, func)
        _sections.append((v, title))
        return v
    return decorator


@section('Featured')
def featured(request):
    return Addon.objects.featured(request.APP)


@section('Category Featured')
def category_featured(request):
    return Addon.objects.category_featured()


@section('Featured + Category Featured')
def combo(request):
    o = Addon.objects
    return o.featured(request.APP) | o.category_featured()


@section('Popular')
def popular(request):
    return Addon.objects.order_by('-weekly_downloads')
