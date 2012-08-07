import caching.base as caching
from jingo import env, register
import jinja2

import amo
from addons.models import AddonCategory, Category
from translations.query import order_by_translation


#TODO: This is pretty much a copy of addons/helpers.py (duplicate code)
@register.inclusion_tag('themes/includes/theme_preview.html')
@jinja2.contextfunction
def theme_preview(context, persona, size='large', linked=True, extra=None,
                  details=False, title=False, caption=False, url=None,
                  landing=False):
    preview_map = {'large': persona.preview_url,
                   'small': persona.thumb_url}
    addon = persona.addon
    c = dict(context.items())
    c.update({'persona': persona, 'addon': addon, 'linked': linked,
              'size': size, 'preview': preview_map[size], 'extra': extra,
              'details': details, 'title': title, 'caption': caption,
              'url_': url, 'landing': landing})
    return c


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
