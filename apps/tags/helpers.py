import jinja2

from jingo import register, env


@register.function
@jinja2.contextfunction
def tag_list(context, addon, dev_tags=None, user_tags=None):
    """Display list of tags, with delete buttons."""
    if not dev_tags and not user_tags:
        return ''
    if not dev_tags:
        dev_tags = []
    if not user_tags:
        user_tags = []

    c = {
        'request': context['request'],
        'addon': addon,
        'dev_tags': dev_tags,
        'user_tags': user_tags,
    }
    t = env.get_template('tags/tag_list.html').render(**c)
    return jinja2.Markup(t)
