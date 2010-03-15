from django.conf import settings

import jinja2

from jingo import register, env
from l10n import ugettext as _, ugettext_lazy as _lazy

import amo


@register.filter
@jinja2.contextfilter
def statusflags(context, addon):
    """experimental/recommended status flags for use as CSS classes"""
    app = context['APP']
    lang = context['LANG']
    if addon.is_unreviewed():
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


@register.function
@jinja2.contextfunction
def separated_list_items(context, addons, src=None):
    c = {'addons': addons, 'APP': context['APP'], 'LANG': context['LANG'],
         'src': src}
    t = env.get_template('addons/separated_list_items.html').render(**c)
    return jinja2.Markup(t)


@register.function
def support_addon(addon):
    t = env.get_template('addons/support_addon.html')
    return jinja2.Markup(t.render(addon=addon))


@register.function
def contribution(addon, text='', src='', show_install=False, show_help=True):
    """
    Show a contribution box.

    Parameters:
        addon
        text: The begging text at the top of the box.
        src: The page where the contribution link is coming from.
        show_install: Whether or not to show the install button.
        show_help: Show "What's this?" link?
    """

    # prepare pledge
    try:
        pledge = addon.pledges.ongoing()[0]
        src = '%s-pledge-%s' % (src, pledge.id)
    except IndexError:
        pledge = None

    t = env.get_template('addons/contribution.html')
    return jinja2.Markup(t.render({
        'MEDIA_URL': settings.MEDIA_URL,
        'addon': addon,
        'text': text,
        'src': src,
        'show_install': show_install,
        'show_help': show_help,
        'has_suggested': bool(addon.suggested_amount),
        'pledge': pledge
    }))
