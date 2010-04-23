from jingo import register, env
import jinja2

from access import acl


@register.inclusion_tag('tags/tag_list.html')
@jinja2.contextfunction
def tag_list(context, addon, dev_tags=[], user_tags=[]):
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
