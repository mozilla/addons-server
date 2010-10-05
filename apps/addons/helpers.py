from django.conf import settings

import jinja2

from jingo import register, env
from tower import ugettext as _

from . import buttons


register.function(buttons.install_button)
register.function(buttons.big_install_button)


@register.filter
@jinja2.contextfilter
def statusflags(context, addon):
    """unreviewed/recommended status flags for use as CSS classes"""
    app = context['APP']
    lang = context['LANG']
    if addon.is_unreviewed():
        return 'unreviewed'
    elif addon.is_featured(app, lang) or addon.is_category_featured(app, lang):
        return 'featuredaddon'
    elif addon.is_selfhosted():
        return 'selfhosted'
    else:
        return ''


@register.filter
@jinja2.contextfilter
def flag(context, addon):
    """unreviewed/recommended flag heading."""
    status = statusflags(context, addon)
    msg = {'unreviewed': _('Not Reviewed'), 'featuredaddon': _('Featured'),
           'selfhosted': _('Self Hosted')}
    if status:
        return jinja2.Markup(u'<h5 class="flag">%s</h5>' % msg[status])
    else:
        return ''


@register.function
def support_addon(addon):
    t = env.get_template('addons/support_addon.html')
    return jinja2.Markup(t.render(addon=addon))


@register.inclusion_tag('addons/performance_note.html')
@jinja2.contextfunction
def performance_note(context, amount, listing=False):
    return dict(listing=listing, amount=amount)


@register.inclusion_tag('addons/contribution.html')
@jinja2.contextfunction
def contribution(context, addon, text='', src='', show_install=False,
                 show_help=True):
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

    has_suggested = bool(addon.suggested_amount)
    return new_context(**locals())


@register.inclusion_tag('addons/review_list_box.html')
@jinja2.contextfunction
def review_list_box(context, addon, reviews):
    """Details page: Show a box with three add-on reviews."""
    c = dict(context.items())
    c.update({'addon': addon,
              'reviews': reviews,
             })
    return c


@register.inclusion_tag('addons/review_add_box.html')
@jinja2.contextfunction
def review_add_box(context, addon):
    """Details page: Show a box for the user to post a review."""
    c = dict(context.items())
    c['addon'] = addon
    return c


@register.inclusion_tag('addons/tags_box.html')
@jinja2.contextfunction
def tags_box(context, addon, dev_tags, user_tags, current_user_tags=[]):
    """
    Details page: Show a box with existing tags along with a form to add new
    ones.
    """
    c = dict(context.items())
    c.update({'addon': addon,
              'dev_tags': dev_tags,
              'user_tags': user_tags})
    return c


@register.inclusion_tag('addons/listing/items.html')
@jinja2.contextfunction
def addon_listing_items(context, addons, show_date=False, src=None,
                       notes={}):
    return new_context(**locals())


@register.inclusion_tag('addons/listing/items_compact.html')
@jinja2.contextfunction
def addon_listing_items_compact(context, addons, show_date=False,
                                src=None):
    return new_context(**locals())


@register.inclusion_tag('addons/listing_header.html')
@jinja2.contextfunction
def addon_listing_header(context, url_base, sort_opts, selected,
                         unreviewed=None, show_unreviewed=True):
    return new_context(**locals())


def new_context(context, **kw):
    c = dict(context.items())
    c.update(kw)
    return c


@register.inclusion_tag('addons/persona_preview.html')
@jinja2.contextfunction
def persona_preview(context, persona, size='large', linked=True, extra=None,
                    details=False):
    preview_map = {'large': persona.preview_url,
                   'small': persona.thumb_url}

    c = dict(context.items())
    c.update({'persona': persona, 'addon': persona.addon, 'linked': linked,
              'size': size, 'preview': preview_map[size], 'extra': extra,
              'details': details})
    return c


@register.inclusion_tag('addons/persona_grid.html')
@jinja2.contextfunction
def persona_grid(context, addons):
    return new_context(**locals())
