import jinja2

from jingo import register


@register.filter
@jinja2.contextfilter
def statusflags(context, addon):
    """experimental/recommended status flags for use as CSS classes"""
    app = context['APP']
    lang = context['LANG']
    if addon.is_experimental():
        return 'experimental'
    elif addon.is_featured(app, lang) or addon.is_category_featured(app, lang):
        return 'recommended'
    else:
        return ''
