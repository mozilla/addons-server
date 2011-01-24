import random

import jinja2

from jingo import register, env
from tower import ugettext as _

from . import buttons
import amo


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
    return jinja2.Markup(t.render(addon=addon, amo=amo))


@register.inclusion_tag('addons/performance_note.html')
@jinja2.contextfunction
def performance_note(context, amount, listing=False):
    return new_context(**locals())


@register.inclusion_tag('addons/contribution.html')
@jinja2.contextfunction
def contribution(context, addon, text=None, src='', show_install=False,
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
    has_suggested = bool(addon.suggested_amount)
    return new_context(**locals())


@register.inclusion_tag('addons/review_list_box.html')
@jinja2.contextfunction
def review_list_box(context, addon, reviews):
    """Details page: Show a box with three add-on reviews."""
    c = dict(context.items())
    c.update(addon=addon, reviews=reviews)
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
def tags_box(context, addon, tags=None):
    """
    Details page: Show a box with existing tags along with a form to add new
    ones.
    """
    c = dict(context.items())
    c.update({'addon': addon,
              'tags': tags})
    return c


@register.filter
@jinja2.contextfilter
def shuffle_boundary(context, addons, boundary=None):
    if not boundary:
        return addons
    split = addons[:boundary], addons[boundary:]
    for s in split:
        random.shuffle(s)
    return split[0] + split[1]


@register.inclusion_tag('addons/listing/items.html')
@jinja2.contextfunction
def addon_listing_items(context, addons, show_date=False, src=None,
                       notes={}):
    return new_context(**locals())


@register.inclusion_tag('addons/listing/items_compact.html')
@jinja2.contextfunction
def addon_listing_items_compact(context, addons, boundary=0,
                                show_date=False, src=None):
    if show_date == 'featured' and boundary:
        addons = shuffle_boundary(context, list(addons), boundary)
    return new_context(**locals())


@register.inclusion_tag('addons/listing_header.html')
@jinja2.contextfunction
def addon_listing_header(context, url_base, sort_opts, selected):
    return new_context(**locals())


def new_context(context, **kw):
    c = dict(context.items())
    c.update(kw)
    return c


@register.inclusion_tag('addons/persona_preview.html')
@jinja2.contextfunction
def persona_preview(context, persona, size='large', linked=True, extra=None,
                    details=False, title=False, disco_link=False):
    preview_map = {'large': persona.preview_url,
                   'small': persona.thumb_url}

    c = dict(context.items())
    c.update({'persona': persona, 'addon': persona.addon, 'linked': linked,
              'size': size, 'preview': preview_map[size], 'extra': extra,
              'details': details, 'title': title, 'disco_link': disco_link})
    return c


@register.inclusion_tag('addons/persona_grid.html')
@jinja2.contextfunction
def persona_grid(context, addons):
    return new_context(**locals())


@register.inclusion_tag('addons/report_abuse.html')
@jinja2.contextfunction
def addon_report_abuse(context, hide, addon):
    return new_context(**locals())
