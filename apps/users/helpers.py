import random

import jinja2

from jingo import register, env
from tower import ugettext as _


@register.function
def emaillink(email, title=None):
    if not email:
        return ""

    fallback = email[::-1]  # reverse
    # inject junk somewhere
    i = random.randint(0, len(email) - 1)
    fallback = u"%s%s%s" % (jinja2.escape(fallback[:i]),
                            u'<span class="i">null</span>',
                            jinja2.escape(fallback[i:]))
    # replace @ and .
    fallback = fallback.replace('@', '&#x0040;').replace('.', '&#x002E;')

    if title:
        title = jinja2.escape(title)
    else:
        title = '<span class="emaillink">%s</span>' % fallback

    node = u'<a href="#">%s</a><span class="emaillink js-hidden">%s</span>' % (
        title, fallback)
    return jinja2.Markup(node)


@register.filter
def user_link(user):
    if not user:
        return ''
    return jinja2.Markup(_user_link(user))


@register.function
def users_list(users, size=None):
    if not users:
        return ''

    tail = []
    if size and size < len(users):
        users = users[:size]
        tail = [_('others', 'user_list_others')]

    return jinja2.Markup(', '.join(map(_user_link, users) + tail))


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


@register.inclusion_tag('users/report_abuse.html')
@jinja2.contextfunction
def user_report_abuse(context, hide, profile):
    new = dict(context.items())
    new.update({'hide': hide, 'profile': profile,
                'abuse_form': context['abuse_form']})
    return new
