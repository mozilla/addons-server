from jingo import register
import jinja2
from access import acl
from amo.urlresolvers import reverse


@register.inclusion_tag('tags/tag_list.html')
@jinja2.contextfunction
def tag_list(context, addon, dev_tags=[], user_tags=[],
             current_user_tags=[]):
    """Display list of tags, with delete buttons."""

    c = dict(context.items())

    # admins can delete any tag
    c['is_tag_admin'] = (c['request'].user.is_authenticated() and
                         acl.action_allowed(c['request'], 'Admin',
                                            'DeleteAnyTag'))

    c.update({'addon': addon,
              'dev_tags': dev_tags,
              'user_tags': user_tags})
    return c


def range_convert(value, old_min, old_max, new_min, new_max):
    """
    Utility to tranfer a value (preserving the relative value in
    the range) from its current range to a new one.
    """
    old_range = 1 if old_max - old_min == 0 else old_max - old_min
    new_range = new_max - new_min
    return int(((value - old_min) * new_range) / old_range) + new_min


@register.function
def tag_link(tag, min_count, max_count):
    """create the tag cloud link with the poper tagLevel class"""
    factor = range_convert(tag.tagstat.num_addons, 0, max_count, 1, 10)
    hyperlink = u'<a class="tagLevel%d tag" href="%s">%s</a>'
    return hyperlink % (factor,
                        reverse('tags.detail', args=[tag.tag_text.lower()]),
                        tag.tag_text)
