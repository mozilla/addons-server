from django.conf import settings
from django.utils.encoding import force_text
from django.utils.translation import pgettext

import jinja2
import six

from django_jinja import library

from olympia import amo
from olympia.amo.utils import urlparams


@library.global_function
def emaillink(email, title=None, klass=None):
    if not email:
        return ""

    fallback = email[::-1]  # reverse
    # Inject junk in the middle. (Predictable but allows the content hash for
    # a given page to stay stable).
    i = len(email) - 2
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


@library.filter
def user_link(user):
    if not user:
        return ''
    return jinja2.Markup(_user_link(user))


@library.global_function
def users_list(users, size=None, max_text_length=None):
    if not users:
        return ''

    tail = []
    if size and size < len(users):
        users = users[:size]
        tail = [pgettext('user_list_others', 'others')]

    if max_text_length:
        user_list = [_user_link(user, max_text_length) for user in users]
    else:
        user_list = list(map(_user_link, users))

    return jinja2.Markup(', '.join(user_list + tail))


@library.global_function
@library.render_with('users/helpers/addon_users_list.html')
@jinja2.contextfunction
def addon_users_list(context, addon):
    ctx = dict(context.items())
    ctx.update(addon=addon, amo=amo)
    return ctx


def _user_link(user, max_text_length=None):
    if isinstance(user, six.string_types):
        return user

    if max_text_length and len(user.name) > max_text_length:
        name = user.name[:max_text_length].strip() + '...'
    else:
        name = user.name

    return u'<a href="%s" title="%s">%s</a>' % (
        user.get_url_path(), jinja2.escape(user.name),
        jinja2.escape(force_text(name)))


@library.global_function
@jinja2.contextfunction
def manage_fxa_link(context):
    user = context['user']
    base_url = '{host}/settings'.format(
        host=settings.FXA_CONFIG['default']['content_host'])
    return urlparams(
        base_url, uid=user.fxa_id, email=user.email, entrypoint='addons')
