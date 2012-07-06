from django.conf import settings
from django.shortcuts import get_list_or_404, get_object_or_404, redirect

import amo
from amo.models import manual_order
from browse.views import personas_listing
from addons.decorators import addon_view_factory
from addons.models import Addon, Category, AddonCategory
from addons.views import _category_personas as _category_themes
from discovery.views import get_featured_personas

import jingo
from waffle.decorators import waffle_switch

addon_all_view = addon_view_factory(qs=Addon.objects.all)


@waffle_switch('mkt-themes')
@addon_all_view
def detail(request, addon):
    """Theme details page."""
    theme = addon.persona

    categories = addon.all_categories
    if categories:
        qs = Addon.objects.public().filter(categories=categories[0])
        category_themes = _category_themes(qs, limit=6)
    else:
        category_themes = None

    data = {
        'product': addon,
        'categories': categories,
        'category_themes': category_themes,
        'author_themes': theme.authors_other_addons(request.APP)[:3],
        'theme': theme,
    }
    if not theme.is_new():
        # Remora uses persona.author despite there being a display_username.
        data['author_gallery'] = settings.PERSONAS_USER_ROOT % theme.author

    return jingo.render(request, 'themes/detail.html', data)


@waffle_switch('mkt-themes')
def _landing(request, category=None):
    if category:
        featured = ''
        category = get_list_or_404(
            Category.objects.filter(type=amo.ADDON_PERSONA,
            slug=category))[0]
        popular = (Addon.objects.public()
                   .filter(type=amo.ADDON_PERSONA,
                           addoncategory__category__id=category.id)
                   .order_by('-persona__popularity')[:12])

        categories, filter, base, category = personas_listing(request,
                                                              category.slug)
        ids = AddonCategory.creatured_random(category, request.LANG)
        featured = manual_order(base, ids, pk_name="addons.id")[:12]
    else:
        popular = (Addon.objects.public().filter(type=amo.ADDON_PERSONA)
                   .order_by('-persona__popularity')[:12])
        featured = get_featured_personas(request, num_personas=12)

    return jingo.render(request, 'themes/landing.html', {
        'category': category,
        'popular': popular,
        'featured': featured,
    })


# TODO: sort pages, this function is just a stub.
@waffle_switch('mkt-themes')
def _search(request, category=None):
    from django.http import Http404
    raise Http404

    ctx = {'browse': True}

    if category is not None:
        qs = Category.objects.filter(type=amo.ADDON_PERSONA, weight__gte=0)
        ctx['category'] = get_object_or_404(qs, slug=category)

        # Do a search filtered by this category and sort by Weekly Downloads.
        # TODO: Listen to andy and do not modify `request.GET` but at least
        # the traceback is fixed now.
        request.GET = request.GET.copy()
        request.GET.update({'cat': ctx['category'].id})
        if not request.GET.get('sort'):
            request.GET['sort'] = 'downloads'

    ctx.update(_app_search(request, category=ctx.get('category'), browse=True))

    # If category is not listed as a facet, then remove redirect to search.
    if ctx.get('redirect'):
        return redirect(ctx['redirect'])

    return jingo.render(request, 'search/results.html', ctx)


@waffle_switch('mkt-themes')
def browse_themes(request, category=None):
    if request.GET.get('sort'):
        return _search(request, category)
    else:
        return _landing(request, category)
