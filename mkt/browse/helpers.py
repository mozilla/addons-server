import caching.base as caching
from jingo import env, register
import jinja2

import amo
from addons.models import AddonCategory, Category
from translations.query import order_by_translation


@register.function
def category_slider():
    return caching.cached(lambda: _categories(), 'category-slider-apps')


def _categories():
    public_cats = (AddonCategory.objects
                   .filter(addon__status=amo.STATUS_PUBLIC)
                   .values_list('category', flat=True).distinct())
    categories = Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0,
                                         id__in=public_cats)

    categories = order_by_translation(categories, 'name')
    t = env.get_template('browse/helpers/category_slider.html')
    return jinja2.Markup(t.render(categories=categories))


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
    return caching.cached(lambda: _categories_themes(),
                          'category-slider-themes')


def _categories_themes():
    public_cats = (AddonCategory.objects
                   .filter(addon__status=amo.STATUS_PUBLIC,
                           category__type=amo.ADDON_PERSONA)
                   .values_list('category', flat=True).distinct())
    categories = Category.objects.filter(type=amo.ADDON_PERSONA, weight__gte=0,
                                         id__in=public_cats)
    categories = order_by_translation(categories, 'name')

    t = env.get_template('browse/helpers/category_slider.html')
    return jinja2.Markup(t.render(categories=categories))
