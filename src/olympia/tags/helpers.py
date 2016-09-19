from jingo import register
import jinja2


@register.inclusion_tag('tags/tag_list.html')
@jinja2.contextfunction
def tag_list(context, addon, tags=None):
    """Display list of tags, with delete buttons."""
    if tags is None:
        tags = []

    c = dict(context.items())
    c.update({'addon': addon,
              'tags': tags})
    return c
