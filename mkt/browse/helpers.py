import caching.base as caching
import jinja2
from jingo import env, register

import amo
from addons.models import AddonCategory, Category
from translations.query import order_by_translation

import mkt.carriers
import mkt.regions


@register.function
def category_slider(rand=False, limit=None):
    def render():
        t = env.get_template('browse/helpers/category_slider.html')
        return jinja2.Markup(t.render(categories=_categories(rand, limit)))

    return caching.cached(
        render, 'category-slider-apps-%s-%s' % (rand, limit))


def _categories(rand=False, limit=None):
    categories = Category.objects.filter(
        type=amo.ADDON_WEBAPP, weight__gte=0)

    # If the user has a carrier, show any categories that are either for their
    # carrier or that don't have a carrier. Otherwise, only show apps without
    # a carrier.
    carrier = mkt.carriers.get_carrier_id()
    if carrier:
        categories = categories.extra(
            where=['carrier = %s OR carrier IS NULL'], params=[carrier])
    else:
        categories = categories.filter(carrier__isnull=True)

    # Show any categories that are either for the user's region or that don't
    # have a region. Exclude categories not for the user's region.
    categories = categories.extra(
        where=['(`categories`.`region` = %s OR '
               '`categories`.`region` IS NULL)'],
        params=[mkt.regions.get_region_id()])

    if rand:
        categories = categories.order_by('-weight', '?')
    else:
        categories = categories.order_by('-weight')
        categories = order_by_translation(categories, 'name')

    if limit:
        categories = categories[:limit]

    return categories


@register.filter
@jinja2.contextfilter
def promo_grid(context, products, src=''):
    t = env.get_template('browse/helpers/promo_grid.html')
    return jinja2.Markup(t.render(request=context['request'],
                                  products=products,
                                  src=src))


@register.filter
@jinja2.contextfilter
def promo_slider(context, products, feature=False, src=''):
    t = env.get_template('browse/helpers/promo_slider.html')
    return jinja2.Markup(t.render(request=context['request'],
                                  products=products, feature=feature,
                                  src=src))


@register.function
def category_slider_themes():
    return caching.cached(_categories_themes, 'category-slider-themes')


def _categories_themes():
    public_cats = (AddonCategory.objects
                   .filter(addon__status=amo.STATUS_PUBLIC,
                           category__type=amo.ADDON_PERSONA)
                   .values_list('category', flat=True).distinct())
    categories = (Category.objects
                  .filter(type=amo.ADDON_PERSONA, weight__gte=0,
                          id__in=public_cats)
                  .order_by('-weight'))
    categories = order_by_translation(categories, 'name')

    t = env.get_template('browse/helpers/category_slider.html')
    return jinja2.Markup(t.render(categories=categories))
