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
def promo_grid(context, products):
    t = env.get_template('browse/helpers/promo_grid.html')
    return jinja2.Markup(t.render(products=products))


@register.filter
@jinja2.contextfilter
def promo_slider(context, products, feature=False):
    t = env.get_template('browse/helpers/promo_slider.html')
    return jinja2.Markup(t.render(products=products, feature=feature))
