import jinja2

from jingo import register, env


@register.inclusion_tag('tags/tag_list.html')
@jinja2.contextfunction
def tag_list(context, addon, dev_tags=[], user_tags=[]):
    """Display list of tags, with delete buttons."""

    c = dict(context.items())

    c.update({'addon': addon,
              'dev_tags': dev_tags,
              'user_tags': user_tags})
    return c
