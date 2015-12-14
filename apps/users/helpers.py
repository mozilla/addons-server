import random

from django.utils.encoding import smart_unicode

import jinja2
from jingo import register, env
from tower import ugettext as _

import amo


@register.function
def emaillink(email, title=None, klass=None):
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

    node = (u'<a%s href="#">%s</a><span class="emaillink js-hidden">%s</span>'
            % ((' class="%s"' % klass) if klass else '', title, fallback))
    return jinja2.Markup(node)


@register.filter
def user_link(user):
    if not user:
        return ''
    return jinja2.Markup(_user_link(user))


@register.function
def users_list(users, size=None, max_text_length=None):
    if not users:
        return ''

    tail = []
    if size and size < len(users):
        users = users[:size]
        tail = [_('others', 'user_list_others')]

    if max_text_length:
        user_list = [_user_link(user, max_text_length) for user in users]
    else:
        user_list = map(_user_link, users)

    return jinja2.Markup(', '.join(user_list + tail))


@register.inclusion_tag('users/helpers/addon_users_list.html')
@jinja2.contextfunction
def addon_users_list(context, addon):
    ctx = dict(context.items())
    ctx.update(addon=addon, amo=amo)
    return ctx


def _user_link(user, max_text_length=None):
    if isinstance(user, basestring):
        return user

    username = user.name
    if max_text_length and len(user.name) > max_text_length:
        username = user.name[:max_text_length].strip() + '...'

    return u'<a href="%s" title="%s">%s</a>' % (
        user.get_url_path(), jinja2.escape(user.name),
        jinja2.escape(smart_unicode(username)))


@register.filter
@jinja2.contextfilter
def user_vcard(context, user, table_class='person-info', is_profile=False):
    c = dict(context.items())
    c.update({
        'profile': user,
        'table_class': table_class,
        'is_profile': is_profile
    })
    t = env.get_template('users/vcard.html').render(c)
    return jinja2.Markup(t)


@register.inclusion_tag('users/report_abuse.html')
@jinja2.contextfunction
def user_report_abuse(context, hide, profile):
    new = dict(context.items())
    new.update({'hide': hide, 'profile': profile,
                'abuse_form': context['abuse_form']})
    return new


@register.filter
def contribution_type(type):
    return amo.CONTRIB_TYPES[type]


@register.function
def user_data(user):
    anonymous, currency, email = True, 'USD', ''
    if hasattr(user, 'is_anonymous'):
        anonymous = user.is_anonymous()
    if not anonymous:
        email = user.email

    return {'anonymous': anonymous, 'currency': currency, 'email': email}
