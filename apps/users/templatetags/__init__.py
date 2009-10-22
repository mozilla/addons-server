import jinja2

from jingo import register


@register.filter
def user_link(user):
    return jinja2.Markup('<a href="%s">%s</a>' %
                         (user.get_absolute_url(), user.display_name))
