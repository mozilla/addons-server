import random

import jinja2

from jingo import register, env


@register.filter
def emaillink(email):
    if not email:
        return ""

    fallback = email[::-1] # reverse
    # inject junk somewhere
    i = random.randint(0, len(email)-1)
    fallback = u"%s%s%s" % (fallback[:i], u'<span class="i">null</span>',
                            fallback[i:])
    # replace @ and .
    fallback = fallback.replace('@', '&#x0040;').replace('.', '&#x002E;')

    node = u'<span class="emaillink">%s</span>' % fallback
    return jinja2.Markup(node)


@register.filter
def user_link(user):
    return jinja2.Markup(_user_link(user))


@register.filter
def users_list(users):
    return jinja2.Markup(', '.join(map(_user_link, users)))


def _user_link(user):
    return u'<a href="%s">%s</a>' % (
        user.get_absolute_url(), unicode(jinja2.escape(user.display_name)))


@register.filter
def user_vcard(user, table_class='person-info',
               about_addons=True):
    c = {'profile': user, 'table_class': table_class,
         'about_addons': about_addons}
    t = env.get_template('users/vcard.html').render(**c)
    return jinja2.Markup(t)
