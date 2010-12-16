from jingo import register, env
import jinja2
from access import acl
from amo.urlresolvers import reverse


@register.inclusion_tag('tags/tag_list.html')
@jinja2.contextfunction
def tag_list(context, addon, tags=[]):
    """Display list of tags, with delete buttons."""

    c = dict(context.items())
    c.update({'addon': addon,
              'tags': tags})
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
def tag_link(tag, min_count, max_count, min_level=1):
    """create the tag cloud link with the poper tagLevel class"""
    factor = max(range_convert(tag.tagstat.num_addons, 0, max_count, 1, 10),
                 min_level)
    t = env.get_template('tags/tag_link.html').render({'factor': factor,
                                                       'tag': tag})
    return jinja2.Markup(t)
