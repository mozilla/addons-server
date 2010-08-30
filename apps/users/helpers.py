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
    fallback = u"%s%s%s" % (jinja2.escape(fallback[:i]),
                            u'<span class="i">null</span>',
                            jinja2.escape(fallback[i:]))
    # replace @ and .
    fallback = fallback.replace('@', '&#x0040;').replace('.', '&#x002E;')

    node = u'<span class="emaillink">%s</span>' % fallback
    return jinja2.Markup(node)


@register.filter
def user_link(user):
    if not user:
        return ''
    return jinja2.Markup(_user_link(user))


@register.function
def users_list(users):
    if not users:
        return ''
    return jinja2.Markup(', '.join(map(_user_link, users)))


def _user_link(user):
    if isinstance(user, basestring):
        return user
    return u'<a href="%s">%s</a>' % (
        user.get_url_path(), unicode(jinja2.escape(user.name)))


@register.filter
def user_vcard(user, table_class='person-info',
               about_addons=True):
    c = {'profile': user, 'table_class': table_class,
         'about_addons': about_addons}
    t = env.get_template('users/vcard.html').render(**c)
    return jinja2.Markup(t)
