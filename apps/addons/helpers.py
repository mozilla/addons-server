from django.utils.translation import ugettext as _

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


@register.filter
@jinja2.contextfilter
def flag(context, addon):
    """experimental/recommended flag heading."""
    status = statusflags(context, addon)
    msg = {'experimental': _('Experimental'), 'recommended': _('Recommended')}
    if status:
        return jinja2.Markup(u'<h5 class="flag">%s</h5>' % msg[status])
    else:
        return ''
