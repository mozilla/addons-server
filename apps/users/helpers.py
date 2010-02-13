import jinja2

from jingo import register


@register.filter
def emaillink(email):
    if not email:
        return ""

    fallback = email[::-1] # reverse
    # inject junk somewhere
    i = random.randint(0, len(email)-1)
    fallback = u"%s%s%s" % (jinja2.escape(fallback[:i]),
                            u'<span class="i">null</span>',
                            jinja2.escape(fallback[i:]))
    # replace @ and .
    fallback = fallback.replace('@', '&#x0040;').replace('.', '&#x002E;')

    node = u'<span class="emaillink">%s</span>' % fallback
    return jinja2.Markup(node)


@register.filter
def user_link(user):
    return jinja2.Markup('<a href="%s">%s</a>' %
                         (user.get_absolute_url(), user.display_name))
